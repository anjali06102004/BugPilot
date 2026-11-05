"""Registry regression test: two scans of the same project must deduplicate,
and a previously fixed issue must be flagged as a regression."""

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

DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)
os.environ.setdefault("BUGPILOT_ENV", "development")
os.environ.setdefault("DATABASE_URL", f"sqlite+aiosqlite:///{(DATA_DIR / 'registry.db').as_posix()}")
os.environ.setdefault("EVIDENCE_DIR", str((DATA_DIR / "registry-evidence").as_posix()))

API = "http://127.0.0.1:8012"
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


def run_scan(client: httpx.Client, project_id: str) -> tuple[str, list[dict]]:
    scan = client.post(
        f"{API}/api/v1/scans",
        json={
            "url": f"{FIXTURE}/",
            "project_id": project_id,
            "environment": "development",
            "scope": {"type": "single_url", "interaction_depth": "safe"},
            "config": {
                "max_pages": 1,
                "max_duration_seconds": 60,
                "max_actions": 6,
                "viewports": [{"name": "mobile-390", "width": 390, "height": 844}],
                "categories": ["visual", "responsive", "accessibility", "console", "content"],
            },
        },
    )
    scan.raise_for_status()
    scan_id = scan.json()["id"]
    deadline = time.time() + 120
    while time.time() < deadline:
        data = client.get(f"{API}/api/v1/scans/{scan_id}").json()
        if data["status"] in {"completed", "failed", "cancelled", "stopped"}:
            return scan_id, data["findings"]
        time.sleep(1.5)
    raise SystemExit("scan did not finish")


def main() -> int:
    import subprocess

    py = str(ROOT / ".venv" / "Scripts" / "python.exe")
    if not Path(py).exists():
        py = sys.executable
    env = dict(os.environ)
    fixture = subprocess.Popen(
        [py, "-m", "uvicorn", "server:app", "--host", "127.0.0.1", "--port", "4173"],
        cwd=str(ROOT / "fixtures" / "broken-shop"),
        env=env,
    )
    api = subprocess.Popen(
        [py, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8012"],
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
        with httpx.Client(timeout=30.0) as client:
            project = client.post(
                f"{API}/api/v1/projects",
                json={
                    "name": "Broken Shop",
                    "website_url": f"{FIXTURE}/",
                    "critical_routes": ["/checkout"],
                },
            ).json()
            project_id = project["id"]

            scan1, findings1 = run_scan(client, project_id)
            issues1 = client.get(f"{API}/api/v1/issues?project_id={project_id}").json()
            print(f"scan 1: {len(findings1)} findings, {issues1['total']} registry issues")

            scan2, findings2 = run_scan(client, project_id)
            issues2 = client.get(f"{API}/api/v1/issues?project_id={project_id}").json()
            print(f"scan 2: {len(findings2)} findings, {issues2['total']} registry issues")

            if issues2["total"] != issues1["total"]:
                print("FAIL: repeated scan created duplicate issues")
                return 1
            if not all(i["occurrence_count"] >= 2 for i in issues2["items"]):
                print("FAIL: occurrence counts did not grow")
                print([(i["title"], i["occurrence_count"]) for i in issues2["items"]])
                return 1
            print("OK: second scan reused canonical issues and incremented occurrences")

            target = issues2["items"][0]
            detail = client.get(f"{API}/api/v1/issues/{target['id']}").json()
            print(
                f"target issue: {detail['title']} status={detail['status']} occ={detail['occurrence_count']}"
            )
            print("occurrences:", len(detail["occurrences"]), "evidence:", len(detail["evidence"]))
            if len(detail["occurrences"]) < 2:
                print("FAIL: expected one occurrence per scan")
                return 1

            for status in ("triaged", "confirmed", "in_progress", "fixed", "verified"):
                r = client.post(
                    f"{API}/api/v1/issues/{target['id']}/transition",
                    json={"status": status, "body": f"moved to {status}", "author": "qa"},
                )
                if r.status_code != 200:
                    print(f"FAIL: transition to {status} returned {r.status_code}: {r.text}")
                    return 1
            print("OK: lifecycle transitions triaged -> confirmed -> in_progress -> fixed -> verified")

            bad = client.post(
                f"{API}/api/v1/issues/{target['id']}/transition",
                json={"status": "new"},
            )
            if bad.status_code != 409:
                print(f"FAIL: invalid transition should be rejected, got {bad.status_code}")
                return 1
            print("OK: invalid transition rejected with 409")

            note = client.post(
                f"{API}/api/v1/issues/{target['id']}/notes",
                json={"body": "Verified in staging", "author": "qa"},
            )
            if note.status_code != 200:
                print("FAIL: could not add note")
                return 1

            scan3, findings3 = run_scan(client, project_id)
            reopened = client.get(f"{API}/api/v1/issues/{target['id']}").json()
            print(f"after scan 3: status={reopened['status']} regression={reopened['is_regression']}")
            if reopened["status"] != "reopened" or not reopened["is_regression"]:
                print("FAIL: reappearing fixed issue was not flagged as a regression")
                return 1
            print("OK: regression detected and issue reopened")

            stats = client.get(f"{API}/api/v1/issues/stats?project_id={project_id}").json()
            print("stats:", stats["total"], "open", stats["open"], "regressions", stats["regressions"])

            grouped = client.get(f"{API}/api/v1/issues?group_by=severity").json()
            print("grouped by severity:", {k: len(v) for k, v in grouped.get("groups", {}).items()})
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
