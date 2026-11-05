"""Regression check: a single-URL scan must still perform interactions.

The page budget bounds how many distinct pages are opened. It must not stop
the agent before it has tested the page the user selected, otherwise a
single-URL scan would only ever report static defects.
"""

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

DATA = ROOT / "data"
DATA.mkdir(exist_ok=True)
os.environ.setdefault("BUGPILOT_ENV", "development")
os.environ.setdefault("DATABASE_URL", f"sqlite+aiosqlite:///{(DATA / 'single.db').as_posix()}")
os.environ.setdefault("EVIDENCE_DIR", str((DATA / "single-evidence").as_posix()))

API = "http://127.0.0.1:8013"
FIXTURE = "http://127.0.0.1:4173"


def wait_for(url: str, timeout: float = 40.0) -> None:
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

    py = str(ROOT / ".venv" / "Scripts" / "python.exe")
    if not Path(py).exists():
        py = sys.executable
    env = dict(os.environ)
    log_dir = DATA / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    def spawn(name, args, cwd, extra=None):
        log = open(log_dir / f"{name}.log", "w", encoding="utf-8")
        return subprocess.Popen(
            args, cwd=str(cwd), env={**env, **(extra or {})}, stdout=log, stderr=subprocess.STDOUT
        )

    fixture = spawn(
        "fixture",
        [py, "-m", "uvicorn", "server:app", "--host", "127.0.0.1", "--port", "4173"],
        ROOT / "fixtures" / "broken-shop",
    )
    api = spawn(
        "api",
        [py, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8013"],
        ROOT / "services" / "api",
        {"PYTHONPATH": f"{ROOT / 'packages' / 'core'};{ROOT / 'services' / 'api'}"},
    )
    worker = spawn(
        "worker",
        [py, "-m", "worker.main"],
        ROOT / "services" / "browser-worker",
        {"PYTHONPATH": f"{ROOT / 'packages' / 'core'};{ROOT / 'services' / 'browser-worker'}"},
    )
    try:
        wait_for(f"{FIXTURE}/health")
        wait_for(f"{API}/health")
        with httpx.Client(timeout=60.0) as client:
            # max_pages=1 is exactly the configuration the dashboard and the
            # extension use for a single URL scan.
            scan = client.post(
                f"{API}/api/v1/scans",
                json={
                    "url": f"{FIXTURE}/",
                    "project_name": "Broken Shop",
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
                data = client.get(f"{API}/api/v1/scans/{scan_id}").json()
                if data["status"] in {"completed", "failed", "cancelled"}:
                    break
                time.sleep(2)
            print("status:", data["status"])
            print("pages:", data["pages_tested"])
            print("actions:", data["actions_taken"])
            print("stop_reason:", data["stop_reason"])
            print("findings:", len(data["findings"]))
            if data["actions_taken"] < 1:
                print("FAIL: a single URL scan must perform interactions on the selected page")
                return 1
            if data["pages_tested"] != 1:
                print("FAIL: a single URL scan must not open other pages")
                return 1
            print("OK: single URL scan interacted with the page and stayed on one page")
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
