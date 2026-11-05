"""End-to-end smoke test: fixture site + API + worker, real browser scan."""

from __future__ import annotations

import os
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

os.environ.setdefault("BUGPILOT_ENV", "development")
DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)
os.environ.setdefault("DATABASE_URL", f"sqlite+aiosqlite:///{(DATA_DIR / 'e2e.db').as_posix()}")
os.environ.setdefault("EVIDENCE_DIR", str((DATA_DIR / "e2e-evidence").as_posix()))

API = "http://127.0.0.1:8011"
FIXTURE = "http://127.0.0.1:4173"


def wait_for(url: str, timeout: float = 30.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            httpx.get(url, timeout=2.0)
            return
        except Exception:
            time.sleep(0.3)
    raise SystemExit(f"timed out waiting for {url}")


def main() -> int:
    import subprocess

    env = dict(os.environ)
    py = str(ROOT / ".venv" / "Scripts" / "python.exe")
    if not Path(py).exists():
        py = sys.executable

    fixture = subprocess.Popen(
        [py, "-m", "uvicorn", "server:app", "--host", "127.0.0.1", "--port", "4173"],
        cwd=str(ROOT / "fixtures" / "broken-shop"),
        env=env,
    )
    api = subprocess.Popen(
        [py, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8011"],
        cwd=str(ROOT / "services" / "api"),
        env={**env, "PYTHONPATH": f"{ROOT / 'packages' / 'core'};{ROOT / 'services' / 'api'}"},
    )
    worker = subprocess.Popen(
        [py, "-m", "worker.main"],
        cwd=str(ROOT / "services" / "browser-worker"),
        env={
            **env,
            "PYTHONPATH": f"{ROOT / 'packages' / 'core'};{ROOT / 'services' / 'browser-worker'}",
        },
    )
    try:
        wait_for(f"{FIXTURE}/health")
        wait_for(f"{API}/health")
        print("servers up")

        with httpx.Client(timeout=30.0) as client:
            scan = client.post(
                f"{API}/api/v1/scans",
                json={
                    "url": f"{FIXTURE}/",
                    "project_name": "Broken Shop",
                    "environment": "development",
                    "scope": {"type": "single_url", "interaction_depth": "safe"},
                    "config": {
                        "max_pages": 3,
                        "max_duration_seconds": 90,
                        "max_actions": 12,
                        "viewports": [{"name": "mobile-390", "width": 390, "height": 844}],
                        "categories": [
                            "visual",
                            "responsive",
                            "accessibility",
                            "console",
                            "network",
                            "content",
                            "forms",
                        ],
                    },
                },
            )
            scan.raise_for_status()
            scan_id = scan.json()["id"]
            print("scan created", scan_id)

            deadline = time.time() + 120
            status = ""
            while time.time() < deadline:
                data = client.get(f"{API}/api/v1/scans/{scan_id}").json()
                status = data["status"]
                if status in {"completed", "failed", "cancelled", "stopped"}:
                    break
                time.sleep(2)
            print("final status:", status)

            data = client.get(f"{API}/api/v1/scans/{scan_id}").json()
            print("pages:", data["pages_tested"], "actions:", data["actions_taken"])
            print("events:", len(data["events"]))
            print("findings:", len(data["findings"]))
            for f in data["findings"][:12]:
                print(f"  - [{f['severity']}/{f['priority']}] {f['title']} ({f['confidence_label']})")

            issues = client.get(f"{API}/api/v1/issues").json()
            print("registry issues:", issues["total"])
            for i in issues["items"][:12]:
                print(
                    f"  * [{i['severity']}/{i['priority']}] {i['title']} status={i['status']} occ={i['occurrence_count']}"
                )

            report = client.get(f"{API}/api/v1/reports/scan/{scan_id}")
            print("report status:", report.status_code, "len", len(report.json()["markdown"]))

            md = client.get(f"{API}/api/v1/reports/scan/{scan_id}.md")
            print("md export:", md.status_code, len(md.content))
            pdf = client.get(f"{API}/api/v1/reports/scan/{scan_id}.pdf")
            print("pdf export:", pdf.status_code, len(pdf.content), pdf.headers.get("content-type"))
            z = client.get(f"{API}/api/v1/reports/scan/{scan_id}.zip")
            print("zip export:", z.status_code, len(z.content))
            if status != "completed":
                return 1
            return 0
    finally:
        for proc in (worker, api, fixture):
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except Exception:
                proc.kill()


if __name__ == "__main__":
    raise SystemExit(main())
