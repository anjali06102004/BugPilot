"""Shared pytest configuration.

The monorepo packages are put on the import path and every test run works
against an isolated SQLite database and evidence directory, so tests never
touch a developer's local data.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for path in (
    ROOT / "packages" / "core",
    ROOT / "services" / "api",
    ROOT / "services" / "browser-worker",
):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

_TMP = Path(tempfile.mkdtemp(prefix="bugpilot-tests-"))
os.environ["BUGPILOT_ENV"] = "development"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{(_TMP / 'test.db').as_posix()}"
os.environ["EVIDENCE_DIR"] = str(_TMP / "evidence")
os.environ["AI_PROVIDER"] = "local"
os.environ["EVIDENCE_PUBLIC"] = "false"
os.environ.pop("GEMINI_API_KEY", None)
os.environ.pop("OPENAI_API_KEY", None)
