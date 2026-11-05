"""Evidence storage.

Artifacts (screenshots, DOM excerpts, logs) are stored outside database rows by
a small adapter so the storage backend can change without touching callers.

Two adapters ship today:

* ``local``  - writes under ``settings.evidence_dir`` (development default)
* ``s3``     - reserved for production object storage; raises a clear error
                until credentials are configured rather than pretending to work

The adapter also owns the safety concerns that are easy to forget: size
limits, redaction of secrets found in page text, and signed access tokens so
an evidence URL is not a public URL.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from bugpilot_core.config import Settings

ALLOWED_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".txt", ".json", ".html", ".log"}

# Values that must never be persisted verbatim in evidence.
REDACTION_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("email", re.compile(r"[\w.+-]+@[\w-]+\.[\w.]{2,}")),
    ("bearer_token", re.compile(r"(?i)\b(bearer\s+)[A-Za-z0-9._\-]{12,}")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}")),
    ("api_key", re.compile(r"(?i)\b(api[_\- ]?key|secret|token|password)\b\s*[:=]\s*\S{6,}")),
    ("credit_card", re.compile(r"\b(?:\d[ -]*?){13,19}\b")),
    ("ssn", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
]

REDACTED = "[redacted]"


def redact_text(text: str) -> str:
    """Remove credential-shaped substrings from free text."""
    result = text
    for name, pattern in REDACTION_PATTERNS:
        if name == "email":
            result = pattern.sub(REDACTED, result)
        elif name == "bearer_token":
            result = pattern.sub(lambda m: m.group(1) + REDACTED, result)
        else:
            result = pattern.sub(REDACTED, result)
    return result


def redact_payload(value: Any, *, max_length: int = 4000) -> Any:
    """Recursively redact a JSON-ish payload and cap its size."""
    if isinstance(value, str):
        return redact_text(value)[:max_length]
    if isinstance(value, dict):
        return {str(k): redact_payload(v, max_length=max_length) for k, v in value.items()}
    if isinstance(value, list):
        return [redact_payload(v, max_length=max_length) for v in value]
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return redact_text(str(value))[:max_length]


class EvidenceError(RuntimeError):
    pass


@dataclass
class StoredEvidence:
    kind: str
    path: str
    size: int
    redacted: bool = False


class EvidenceStore:
    """Base interface implemented by every storage backend."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._secret = self._resolve_secret(settings)

    @staticmethod
    def _resolve_secret(settings: Settings) -> bytes:
        if settings.evidence_signing_secret:
            return settings.evidence_signing_secret.encode()
        if settings.bugpilot_env == "production":
            raise EvidenceError("EVIDENCE_SIGNING_SECRET must be set in production to sign evidence URLs.")
        # Development fallback: stable per-process secret so links keep working
        # for the lifetime of the server.
        return secrets.token_bytes(32)

    # -- signing ---------------------------------------------------------
    def sign(self, session_id: str, filename: str) -> str:
        payload = f"{session_id}/{filename}".encode()
        mac = hmac.new(self._secret, payload, hashlib.sha256).hexdigest()[:32]
        return base64.urlsafe_b64encode(f"{payload.decode()}:{mac}".encode()).decode().rstrip("=")

    def verify(self, token: str) -> tuple[str, str] | None:
        try:
            padding = "=" * (-len(token) % 4)
            raw = base64.urlsafe_b64decode(token + padding).decode()
        except Exception:
            return None
        if ":" not in raw:
            return None
        path, _, mac = raw.rpartition(":")
        expected = hmac.new(self._secret, path.encode(), hashlib.sha256).hexdigest()[:32]
        if not hmac.compare_digest(expected, mac):
            return None
        if "/" not in path:
            return None
        session_id, _, filename = path.partition("/")
        if not session_id or not filename or "/" in filename:
            return None
        return session_id, filename

    # -- storage ---------------------------------------------------------
    def save(
        self,
        session_id: str,
        filename: str,
        data: bytes,
        *,
        kind: str = "file",
        redacted: bool = False,
    ) -> StoredEvidence:
        if len(data) > self.settings.evidence_max_bytes:
            raise EvidenceError(f"Evidence exceeds the {self.settings.evidence_max_bytes} byte limit.")
        suffix = Path(filename).suffix.lower()
        if suffix not in ALLOWED_SUFFIXES:
            raise EvidenceError(f"Evidence file type '{suffix}' is not allowed.")
        target = self._target(session_id, filename)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return StoredEvidence(kind=kind, path=str(target), size=len(data), redacted=redacted)

    def save_text(
        self,
        session_id: str,
        filename: str,
        text: str,
        *,
        kind: str = "text",
        redact: bool | None = None,
    ) -> StoredEvidence:
        should_redact = self.settings.redact_sensitive if redact is None else redact
        content = redact_text(text) if should_redact else text
        return self.save(
            session_id,
            filename,
            content.encode("utf-8"),
            kind=kind,
            redacted=should_redact,
        )

    def read(self, session_id: str, filename: str) -> bytes:
        target = self._target(session_id, filename)
        if not target.exists():
            raise EvidenceError("Evidence not found")
        return target.read_bytes()

    def path_for(self, session_id: str, filename: str) -> Path:
        return self._target(session_id, filename)

    def purge_older_than(self, cutoff_timestamp: float) -> int:
        """Delete artifacts older than the given unix timestamp."""
        removed = 0
        root = self.settings.evidence_dir
        if not root.exists():
            return 0
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            if path.stat().st_mtime < cutoff_timestamp:
                path.unlink()
                removed += 1
        return removed

    def _target(self, session_id: str, filename: str) -> Path:
        safe_session = _safe_component(session_id)
        safe_name = _safe_component(filename)
        return self.settings.evidence_dir / safe_session / safe_name


def _safe_component(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]", "_", value or "")
    cleaned = cleaned.lstrip(".") or "file"
    return cleaned[:120]


class LocalEvidenceStore(EvidenceStore):
    pass


class S3EvidenceStore(EvidenceStore):
    """Placeholder for object storage.

    It refuses to pretend: without a bucket configured it raises immediately so
    no evidence is silently written to a temporary local directory in
    production.
    """

    def __init__(self, settings: Settings) -> None:
        super().__init__(settings)
        self.bucket = ""

    def save(self, session_id: str, filename: str, data: bytes, *, kind: str = "file") -> StoredEvidence:
        raise EvidenceError(
            "S3 evidence storage is not configured. Set EVIDENCE_STORAGE=local or provide bucket credentials."
        )


def build_evidence_store(settings: Settings) -> EvidenceStore:
    if settings.evidence_storage.lower() == "s3":
        return S3EvidenceStore(settings)
    return LocalEvidenceStore(settings)
