from __future__ import annotations

from pathlib import Path

import pytest
from bugpilot_core.config import Settings
from bugpilot_core.evidence import (
    EvidenceError,
    LocalEvidenceStore,
    redact_payload,
    redact_text,
)


def store(tmp_path: Path) -> LocalEvidenceStore:
    settings = Settings(
        evidence_dir=tmp_path,
        evidence_signing_secret="test-secret",
        evidence_max_bytes=1024,
    )
    return LocalEvidenceStore(settings)


def test_redacts_common_secrets():
    text = (
        "contact alice@example.com token=supersecretvalue "
        "Authorization: Bearer abcdefghijklmnop password: hunter2 "
        "card 4111 1111 1111 1111"
    )
    cleaned = redact_text(text)
    assert "alice@example.com" not in cleaned
    assert "supersecretvalue" not in cleaned
    assert "abcdefghijklmnop" not in cleaned
    assert "4111" not in cleaned
    assert "[redacted]" in cleaned


def test_redacts_nested_payloads_and_caps_size():
    payload = {"user": {"email": "bob@example.com"}, "log": "x" * 10000}
    cleaned = redact_payload(payload, max_length=50)
    assert cleaned["user"]["email"] == "[redacted]"
    assert len(cleaned["log"]) == 50


def test_signed_round_trip():
    s = store(Path("./data"))
    token = s.sign("session-1", "shot.png")
    assert s.verify(token) == ("session-1", "shot.png")


def test_rejects_tampered_token():
    s = store(Path("./data"))
    token = s.sign("session-1", "shot.png")
    assert s.verify(token[:-2] + "aa") is None


def test_rejects_path_traversal():
    s = store(Path("./data"))
    assert s.verify("../../etc/passwd") is None


def test_rejects_oversized_evidence(tmp_path):
    s = store(tmp_path)
    with pytest.raises(EvidenceError):
        s.save("s1", "big.png", b"x" * 5000)


def test_rejects_disallowed_extension(tmp_path):
    s = store(tmp_path)
    with pytest.raises(EvidenceError):
        s.save("s1", "evil.exe", b"payload")


def test_saves_and_reads_text_with_redaction(tmp_path):
    s = store(tmp_path)
    stored = s.save_text("s1", "dom.txt", "email: carol@example.com", kind="dom")
    assert stored.redacted is True
    assert "carol@example.com" not in s.read("s1", "dom.txt").decode()


def test_production_requires_signing_secret(tmp_path):
    with pytest.raises(EvidenceError):
        LocalEvidenceStore(
            Settings(
                bugpilot_env="production",
                evidence_dir=tmp_path,
                evidence_signing_secret="",
            )
        )
