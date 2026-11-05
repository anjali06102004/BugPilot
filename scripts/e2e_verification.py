"""Real fix-verification run against the fixture site.

Proves the three outcomes the product promises:

1. a bug that still exists after replay is `still_failing` and reopens,
2. an unreachable reproduction is `inconclusive`, never `fixed`,
3. every attempt is stored as an auditable verification record.
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
os.environ.setdefault("DATABASE_URL", f"sqlite+aiosqlite:///{(DATA / 'verify.db').as_posix()}")
os.environ.setdefault("EVIDENCE_DIR", str((DATA / "verify-evidence").as_posix()))

API = "http://127.0.0.1:8015"
FIXTURE = "http://127.0.0.1:4173"


def wait_for(url: str, timeout: float = 60.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if httpx.get(url, timeout=2.0).status_code < 500:
                return
        except Exception:
            pass
        time.sleep(0.4)
    raise SystemExit(f"timed out waiting for {url}")


def run_scan(client: httpx.Client) -> tuple[str, str, str]:
    project = client.post(
        f"{API}/api/v1/projects",
        json={"name": "Verify demo", "website_url": f"{FIXTURE}/"},
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
                "max_actions": 6,
                "max_duration_seconds": 90,
                "viewports": [{"name": "mobile-390", "width": 390, "height": 844}],
            },
        },
    ).json()
    deadline = time.time() + 150
    while time.time() < deadline:
        detail = client.get(f"{API}/api/v1/scans/{scan['id']}").json()
        if detail["status"] in {"completed", "failed", "cancelled"}:
            issues = client.get(f"{API}/api/v1/issues?project_id={project['id']}").json()
            if not issues["items"]:
                raise SystemExit("scan produced no issues to verify")
            element_issue = issues["items"][0]["id"]
            page_issue = next(
                (
                    i["id"]
                    for i in issues["items"]
                    if i.get("category") == "overflow" and not i.get("selector")
                ),
                element_issue,
            )
            return scan["id"], element_issue, page_issue
        time.sleep(2)
    raise SystemExit("scan did not finish")


async def point_issue_at(issue_id: str, url: str) -> None:
    from bugpilot_core.db import SessionLocal, init_db
    from bugpilot_core.db.models import Issue
    from sqlalchemy import select

    await init_db()
    async with SessionLocal() as db:
        issue = (await db.execute(select(Issue).where(Issue.id == issue_id))).scalar_one()
        issue.url = url
        issue.extra = {
            **(issue.extra or {}),
            "reproduction": {
                **(issue.extra or {}).get("reproduction", {}),
                "url": url,
                "selector": None,
                "actions": [],
            },
        }
        await db.commit()


def main() -> int:
    import asyncio
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
        [py, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8015"],
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
        with httpx.Client(timeout=120.0) as client:
            scan_id, issue_id, clean_issue_id = run_scan(client)
            detail = client.get(f"{API}/api/v1/issues/{issue_id}").json()
            reproduction = (detail.get("description") or "")[:60]
            print(f"scan {scan_id} · issue: {detail['title']} · {reproduction!r}")

            # 1. still failing
            result = client.post(
                f"{API}/api/v1/issues/{issue_id}/verify-fix",
                json={"author": "e2e"},
            ).json()
            print("verdict:", result["verdict"], "| status:", result["issue"]["status"])
            print("notes:", result["notes"])
            print("replayed:", result["actions_replayed"], "failed:", result["actions_failed"])
            if result["verdict"] != "still_failing":
                print("FAIL: the unchanged fixture should still reproduce")
                return 1
            if result["issue"]["status"] != "reopened":
                print("FAIL: a still-failing issue must reopen")
                return 1

            history = client.get(f"{API}/api/v1/issues/{issue_id}/verifications").json()
            if history["total"] < 1:
                print("FAIL: verification not recorded")
                return 1
            print("OK: still_failing → reopened, verification recorded")

            # 2. inconclusive
            asyncio.run(point_issue_at(issue_id, "http://127.0.0.1:9/unreachable"))
            result = client.post(
                f"{API}/api/v1/issues/{issue_id}/verify-fix",
                json={"author": "e2e"},
            ).json()
            print("verdict:", result["verdict"], "| status:", result["issue"]["status"])
            print("notes:", result["notes"])
            if result["verdict"] != "inconclusive":
                print("FAIL: an unreachable reproduction must be inconclusive")
                return 1
            if result["issue"]["status"] != "needs_review":
                print("FAIL: inconclusive must not claim a fix")
                return 1
            print("OK: unreachable reproduction → inconclusive → needs_review")

            # 3. fixed: point a selector-less issue at a clean page and replay
            asyncio.run(point_issue_at(clean_issue_id, f"{FIXTURE}/checkout"))
            result = client.post(
                f"{API}/api/v1/issues/{clean_issue_id}/verify-fix",
                json={"author": "e2e"},
            ).json()
            print("verdict:", result["verdict"], "| status:", result["issue"]["status"])
            print("notes:", result["notes"])
            if result["verdict"] != "fixed" or result["issue"]["status"] != "verified":
                print("FAIL: a clean replay should verify the issue")
                return 1
            print("OK: clean replay → fixed → verified")
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
