"""Visual verification: run the whole stack and capture the real UI.

Starts the fixture site, API, worker and the production Next.js build, runs a
scan, then screenshots the dashboard, scan workspace, registry and issue page.
"""

from __future__ import annotations

import os
import shutil
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
for path in (
    ROOT / "packages" / "core",
    ROOT / "services" / "api",
    ROOT / "services" / "browser-worker",
):
    sys.path.insert(0, str(path))

DATA = ROOT / "data"
DATA.mkdir(exist_ok=True)
OUT = Path(os.environ["TEMP"]) / "bugpilot-shots"
OUT.mkdir(exist_ok=True)

os.environ.setdefault("BUGPILOT_ENV", "development")
os.environ.setdefault("DATABASE_URL", f"sqlite+aiosqlite:///{(DATA / 'ui.db').as_posix()}")
os.environ.setdefault("EVIDENCE_DIR", str((DATA / "ui-evidence").as_posix()))

API = "http://127.0.0.1:8000"
WEB = "http://127.0.0.1:3000"
FIXTURE = "http://127.0.0.1:4173"


def wait_for(url: str, timeout: float = 90.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            response = httpx.get(url, timeout=3.0)
            if response.status_code < 500:
                return
        except Exception:
            pass
        time.sleep(0.5)
    raise SystemExit(f"timed out waiting for {url}")


def main() -> int:
    import subprocess

    from playwright.sync_api import sync_playwright

    py = str(ROOT / ".venv" / "Scripts" / "python.exe")
    if not Path(py).exists():
        py = sys.executable
    env = dict(os.environ)
    next_bin = ROOT / "apps" / "web" / "node_modules" / "next" / "dist" / "bin" / "next"

    log_dir = ROOT / "data" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    def spawn(name: str, args: list[str], cwd: Path, extra_env: dict | None = None):
        # Child output goes to a file: inheriting the parent's stdout pipe keeps
        # the caller's terminal waiting for EOF after this script exits.
        log = open(log_dir / f"{name}.log", "w", encoding="utf-8")
        return subprocess.Popen(
            args,
            cwd=str(cwd),
            env={**env, **(extra_env or {})},
            stdout=log,
            stderr=subprocess.STDOUT,
        )

    fixture = spawn(
        "fixture",
        [py, "-m", "uvicorn", "server:app", "--host", "127.0.0.1", "--port", "4173"],
        ROOT / "fixtures" / "broken-shop",
    )
    api = spawn(
        "api",
        [py, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000"],
        ROOT / "services" / "api",
        {"PYTHONPATH": f"{ROOT / 'packages' / 'core'};{ROOT / 'services' / 'api'}"},
    )
    worker = spawn(
        "worker",
        [py, "-m", "worker.main"],
        ROOT / "services" / "browser-worker",
        {"PYTHONPATH": f"{ROOT / 'packages' / 'core'};{ROOT / 'services' / 'browser-worker'}"},
    )
    web = spawn(
        "web",
        [shutil.which("node") or "node", str(next_bin), "start", "-p", "3000", "-H", "127.0.0.1"],
        ROOT / "apps" / "web",
        {"NEXT_PUBLIC_API_URL": API},
    )
    try:
        wait_for(f"{FIXTURE}/health")
        wait_for(f"{API}/health")
        wait_for(WEB)

        with httpx.Client(timeout=60.0) as client:
            project = client.post(
                f"{API}/api/v1/projects",
                json={
                    "name": "Broken Shop",
                    "website_url": f"{FIXTURE}/",
                    "critical_routes": ["/checkout"],
                },
            ).json()
            scan = client.post(
                f"{API}/api/v1/scans",
                json={
                    "url": f"{FIXTURE}/",
                    "project_id": project["id"],
                    "environment": "development",
                    "scope": {"type": "single_url", "interaction_depth": "safe"},
                    "config": {
                        "max_pages": 1,
                        "max_actions": 8,
                        "max_duration_seconds": 90,
                        "viewports": [{"name": "mobile-390", "width": 390, "height": 844}],
                    },
                },
            ).json()
            scan_id = scan["id"]
            deadline = time.time() + 150
            while time.time() < deadline:
                detail = client.get(f"{API}/api/v1/scans/{scan_id}").json()
                if detail["status"] in {"completed", "failed", "cancelled"}:
                    break
                time.sleep(2)
            issues = client.get(f"{API}/api/v1/issues?project_id={project['id']}").json()
            issue_id = issues["items"][0]["id"] if issues["items"] else None
            finding_id = detail["findings"][0]["id"] if detail["findings"] else None
            if issue_id:
                # Record a real verification so the issue page shows its outcome.
                try:
                    client.post(
                        f"{API}/api/v1/issues/{issue_id}/verify-fix",
                        json={"author": "ui-evidence"},
                        timeout=120,
                    )
                except Exception as exc:
                    print("verification skipped:", exc, flush=True)
            print(
                f"scan {scan_id} status={detail['status']} "
                f"findings={len(detail['findings'])} issues={issues['total']}"
            )

        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": 1440, "height": 1000}, device_scale_factor=1)
            page.goto(WEB, wait_until="domcontentloaded")
            page.wait_for_timeout(1200)
            page.screenshot(path=str(OUT / "01-overview.png"), full_page=True)

            page.goto(f"{WEB}/scans/{scan_id}", wait_until="domcontentloaded")
            page.wait_for_timeout(1500)
            page.screenshot(path=str(OUT / "02-scan.png"), full_page=True)

            if finding_id:
                page.goto(f"{WEB}/findings/{finding_id}", wait_until="domcontentloaded")
                page.wait_for_timeout(1200)
                page.screenshot(path=str(OUT / "03-finding.png"), full_page=True)

            page.goto(f"{WEB}/issues", wait_until="domcontentloaded")
            page.wait_for_timeout(1200)
            page.screenshot(path=str(OUT / "04-registry.png"), full_page=True)

            if issue_id:
                page.goto(f"{WEB}/issues/{issue_id}", wait_until="domcontentloaded")
                page.wait_for_timeout(1200)
                page.screenshot(path=str(OUT / "05-issue.png"), full_page=True)

            page.goto(f"{WEB}/reports", wait_until="domcontentloaded")
            page.wait_for_timeout(1000)
            page.screenshot(path=str(OUT / "06-reports.png"), full_page=True)

            page.set_viewport_size({"width": 390, "height": 844})
            page.goto(WEB, wait_until="domcontentloaded")
            page.wait_for_timeout(800)
            page.screenshot(path=str(OUT / "07-mobile.png"), full_page=True)
            browser.close()

        print("screenshots written to", OUT, flush=True)
        return 0
    finally:
        for proc in (web, worker, api, fixture):
            proc.terminate()
            try:
                proc.wait(timeout=15)
            except Exception:
                proc.kill()


if __name__ == "__main__":
    raise SystemExit(main())
