"""Static checks on the browser extension.

There is no browser in CI, so these tests protect the properties that matter
and can be asserted from source: least-privilege permissions, no remote code,
no inline event handlers, and the absence of a "start scanning on install"
path.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

EXTENSION = Path(__file__).resolve().parents[2] / "apps" / "extension"

REQUIRED_FILES = [
    "manifest.json",
    "background.js",
    "content.js",
    "popup.html",
    "popup.js",
    "popup.css",
    "options.html",
    "options.js",
    "icons/icon16.png",
    "icons/icon32.png",
    "icons/icon48.png",
    "icons/icon128.png",
]


def manifest() -> dict:
    return json.loads((EXTENSION / "manifest.json").read_text(encoding="utf-8"))


def test_all_required_files_exist():
    missing = [name for name in REQUIRED_FILES if not (EXTENSION / name).exists()]
    assert not missing, f"missing extension files: {missing}"


def test_manifest_is_v3():
    data = manifest()
    assert data["manifest_version"] == 3
    assert data["background"]["service_worker"] == "background.js"


def test_least_privilege_permissions():
    permissions = set(manifest().get("permissions", []))
    assert permissions == {"activeTab", "scripting", "storage"}
    # Host access must be requested at runtime, not granted to every site.
    assert manifest().get("host_permissions") in (None, [])
    assert "optional_host_permissions" in manifest()


def test_no_remote_code_or_inline_handlers():
    data = manifest()
    csp = data["content_security_policy"]["extension_pages"]
    assert "'self'" in csp
    assert "unsafe-eval" not in csp
    for page in EXTENSION.glob("*.html"):
        content = page.read_text(encoding="utf-8")
        assert "onclick=" not in content
        assert "<script>" not in content
        assert "http://" not in content.replace("http://localhost", "").replace("http://127.0.0.1", "")


def test_extension_never_contains_provider_keys_or_secret_patterns():
    for path in EXTENSION.rglob("*.js"):
        content = path.read_text(encoding="utf-8")
        assert "GEMINI_API_KEY" not in content
        assert "OPENAI_API_KEY" not in content
        assert "apiKey" not in content


def test_enabling_extension_does_not_start_a_scan():
    background = (EXTENSION / "background.js").read_text(encoding="utf-8")
    on_installed = background.split("chrome.runtime.onInstalled")[1].split("});")[0]
    assert "create-scan" not in on_installed
    assert "api(" not in on_installed
    assert "/scans" not in on_installed


def test_scope_is_validated_before_starting():
    popup = (EXTENSION / "popup.js").read_text(encoding="utf-8")
    assert 'state.scope === "selected_element" && !state.element' in popup
    assert "state.categories.size === 0" in popup
    assert "request-permission" in popup


def test_backend_url_is_validated():
    background = (EXTENSION / "background.js").read_text(encoding="utf-8")
    assert "function normalizeBackend" in background
    assert "url.username" in background
    assert "https:" in background


def test_sound_is_off_by_default():
    background = (EXTENSION / "background.js").read_text(encoding="utf-8")
    assert "soundEnabled: false" in background


def test_javascript_syntax_is_valid():
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed in this environment")
    for path in ["background.js", "content.js", "popup.js", "options.js"]:
        result = subprocess.run(
            [node, "--check", str(EXTENSION / path)],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"{path}: {result.stderr}"
