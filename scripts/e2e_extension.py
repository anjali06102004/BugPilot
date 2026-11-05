"""Real-browser verification of the extension and the page overlay.

Runs the API, worker and fixture, completes a real scan, then:

1. loads the unpacked extension in Chromium and screenshots the popup,
2. checks the scope selector and settings persistence,
3. injects the overlay into the fixture page (loopback test hook) and points
   it at the real scan, verifying the docked widget, counts, minimize and the
   element picker.

The overlay is real product code; only the extension<->page transport is
replaced by the loopback hook, because Playwright cannot click the browser's
extension button to grant `activeTab`.
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
OUT = Path(os.environ["TEMP"]) / "bugpilot-extension"
OUT.mkdir(exist_ok=True)

os.environ.setdefault("BUGPILOT_ENV", "development")
os.environ.setdefault("DATABASE_URL", f"sqlite+aiosqlite:///{(DATA / 'extension.db').as_posix()}")
os.environ.setdefault("EVIDENCE_DIR", str((DATA / "extension-evidence").as_posix()))
os.environ["CORS_ORIGINS"] = "http://127.0.0.1:4173"

API = "http://127.0.0.1:8014"
FIXTURE = "http://127.0.0.1:4173"
EXT = ROOT / "apps" / "extension"


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


def run_scan(client: httpx.Client) -> tuple[str, int]:
    project = client.post(
        f"{API}/api/v1/projects",
        json={"name": "Extension demo", "website_url": f"{FIXTURE}/"},
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
            return scan["id"], len(detail["findings"])
        time.sleep(2)
    raise SystemExit("scan did not finish")


def main() -> int:
    import shutil
    import subprocess

    from playwright.sync_api import sync_playwright

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
        [py, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8014"],
        ROOT / "services" / "api",
        {"PYTHONPATH": f"{ROOT / 'packages' / 'core'};{ROOT / 'services' / 'api'}"},
    )
    worker = spawn(
        "worker",
        [py, "-m", "worker.main"],
        ROOT / "services" / "browser-worker",
        {"PYTHONPATH": f"{ROOT / 'packages' / 'core'};{ROOT / 'services' / 'browser-worker'}"},
    )
    user_data = DATA / "chrome-profile"
    if user_data.exists():
        shutil.rmtree(user_data, ignore_errors=True)

    try:
        wait_for(f"{FIXTURE}/health")
        wait_for(f"{API}/health")
        with httpx.Client(timeout=60.0) as client:
            scan_id, finding_count = run_scan(client)
        print(f"scan {scan_id} completed with {finding_count} findings")

        with sync_playwright() as p:
            args = [
                f"--disable-extensions-except={EXT}",
                f"--load-extension={EXT}",
                "--no-first-run",
                "--no-default-browser-check",
            ]
            try:
                context = p.chromium.launch_persistent_context(
                    str(user_data),
                    headless=False,
                    args=args,
                    viewport={"width": 1280, "height": 900},
                )
                mode = "headed"
            except Exception as exc:
                print(f"headed launch failed ({exc}); trying new headless")
                context = p.chromium.launch_persistent_context(
                    str(user_data),
                    headless=True,
                    args=args,
                    viewport={"width": 1280, "height": 900},
                )
                mode = "headless"

            service_worker = context.service_workers[0] if context.service_workers else None
            if service_worker is None:
                service_worker = context.wait_for_event("serviceworker", timeout=20000)
            extension_id = service_worker.url.split("//")[1].split("/")[0]
            print(f"{mode} chromium, extension id {extension_id}")

            # ---- popup ----
            popup = context.new_page()
            popup.set_viewport_size({"width": 380, "height": 820})
            popup.goto(f"chrome-extension://{extension_id}/popup.html")
            popup.wait_for_timeout(900)
            assert popup.is_visible(".scope-grid"), "scope selector missing"
            assert popup.get_attribute('button[data-scope="single_url"]', "aria-checked") == "true"
            popup.click('button[data-scope="full_site"]')
            assert popup.get_attribute('button[data-scope="full_site"]', "aria-checked") == "true"
            assert popup.is_visible("#site-options")
            popup.click('button[data-scope="selected_element"]')
            assert popup.is_visible("#element-panel")
            popup.screenshot(path=str(OUT / "01-popup.png"), full_page=True)

            # settings persist through the service worker
            popup.check("#animation-toggle")
            popup.wait_for_timeout(500)
            stored = popup.evaluate("() => chrome.storage.sync.get(['animationsEnabled'])")
            assert stored["animationsEnabled"] is True
            popup.uncheck("#animation-toggle")
            popup.wait_for_timeout(500)
            stored = popup.evaluate("() => chrome.storage.sync.get(['animationsEnabled'])")
            assert stored["animationsEnabled"] is False
            print("popup: scope selector + settings OK")

            # service worker rejects a bad backend URL
            bad = popup.evaluate(
                "() => new Promise((resolve) => chrome.runtime.sendMessage("
                "{type: 'bugpilot:save-settings', settings: {backendUrl: 'ftp://nope'}}, resolve))"
            )
            assert bad.get("ok") is False, f"bad backend URL accepted: {bad}"
            popup.evaluate(
                "() => new Promise((resolve) => chrome.runtime.sendMessage("
                "{type: 'bugpilot:save-settings', settings: {backendUrl: 'http://127.0.0.1:8014', "
                "appUrl: 'http://localhost:3000'}}, resolve))"
            )
            print("background: backend URL validation OK")

            # ---- overlay on the real page ----
            page = context.new_page()
            page.add_init_script("window.__BUGPILOT_TEST__ = true;")
            page.goto(f"{FIXTURE}/", wait_until="domcontentloaded")
            page.add_script_tag(path=str(EXT / "content.js"))
            page.wait_for_timeout(400)
            page.evaluate(
                """(scanId) => window.dispatchEvent(new CustomEvent('bugpilot:test-attach', {
                    detail: {
                        scanId,
                        scope: { type: 'single_url', summary: 'Single URL: ' + location.href },
                        settings: { backendUrl: 'http://127.0.0.1:8014', appUrl: 'http://localhost:3000',
                                    animationsEnabled: true, overlaysEnabled: true, soundEnabled: false },
                    },
                }))""",
                scan_id,
            )
            page.wait_for_timeout(2500)
            assert page.locator("#bugpilot-overlay-root").count() == 1, "overlay host missing"
            frame = page.locator("#bugpilot-overlay-root .bp-wrap")
            assert frame.is_visible(), "widget not visible"
            title = page.locator("#bugpilot-overlay-root .bp-title").inner_text()
            assert "Inspection complete" in title, f"unexpected widget title: {title}"
            chips = page.locator("#bugpilot-overlay-root .bp-chip").all_inner_texts()
            print("widget counts:", chips)
            total_in_widget = sum(int(chip.split()[0]) for chip in chips if chip.split()[0].isdigit())
            assert total_in_widget == finding_count, (
                f"widget shows {total_in_widget} issues, scan had {finding_count}"
            )
            page.screenshot(path=str(OUT / "02-overlay.png"), full_page=False)

            # minimize persists
            page.locator('#bugpilot-overlay-root [data-action="minimize"]').click()
            page.wait_for_timeout(900)
            assert page.locator("#bugpilot-overlay-root .bp-mini").is_visible()
            page.screenshot(path=str(OUT / "03-overlay-minimized.png"), full_page=False)
            page.locator('#bugpilot-overlay-root [data-action="expand"]').click()
            page.wait_for_timeout(300)
            assert page.locator("#bugpilot-overlay-root .bp-body").is_visible()
            print("overlay: docked widget, counts, minimize/expand OK")

            # element picker
            page.evaluate("() => window.dispatchEvent(new CustomEvent('bugpilot:test-picker'))")
            page.wait_for_timeout(200)
            page.mouse.click(120, 400)
            page.wait_for_timeout(500)
            picked = page.evaluate("() => localStorage.getItem('bugpilot:state')")
            assert picked and "bugpilotPickedElement" in picked, "picker did not record a selection"
            print("overlay: element picker OK")

            context.close()
        print("screenshots in", OUT)
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
