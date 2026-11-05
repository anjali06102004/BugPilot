"""Phase 7 contracts: metrics, worker heartbeat and evidence retention."""

from __future__ import annotations

import os
import time
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.main import app
from bugpilot_core.config import get_settings
from bugpilot_core.db import SessionLocal, init_db
from bugpilot_core.db.models import (
    FindingEvidence,
    Issue,
    IssueEvidence,
    Project,
    TestSession,
    WorkerHeartbeat,
)
from bugpilot_core.evidence import LocalEvidenceStore
from bugpilot_core.retention import purge_empty_dirs, purge_expired_evidence


@pytest.fixture()
def client():
    with TestClient(app) as test_client:
        yield test_client


def test_metrics_shape(client):
    payload = client.get("/api/v1/metrics").json()
    for key in ("version", "event_transport", "queue_depth", "worker", "scans", "issues", "model"):
        assert key in payload
    assert "by_status" in payload["scans"]
    assert "avg_latency_ms" in payload["model"]


def test_worker_heartbeat_is_reported(client):
    worker_id = f"test-worker-{uuid.uuid4().hex[:6]}"
    asyncio_run(_write_heartbeat(worker_id))

    payload = client.get("/api/v1/metrics").json()
    assert payload["worker"]["id"] == worker_id
    assert payload["worker"]["healthy"] is True
    assert payload["worker"]["status"] == "idle"


async def _write_heartbeat(worker_id: str) -> None:
    await init_db()
    async with SessionLocal() as db:
        db.add(
            WorkerHeartbeat(
                worker_id=worker_id,
                status="idle",
                scans_processed=3,
                event_transport="database",
                last_seen_at=datetime.now(UTC),
            )
        )
        await db.commit()


def asyncio_run(coro):
    import asyncio

    return asyncio.run(coro)


async def _seed_retention(tmp_path) -> tuple[str, str]:
    await init_db()
    settings = get_settings()
    old = datetime.now(UTC) - timedelta(days=40)
    async with SessionLocal() as db:
        project = Project(
            id=str(uuid.uuid4()),
            name="Retention",
            website_url="https://shop.example.com/",
            environment="staging",
            evidence_retention_days=30,
        )
        session = TestSession(
            id=str(uuid.uuid4()),
            project_id=project.id,
            start_url="https://shop.example.com/",
            status="completed",
        )
        issue = Issue(
            id=str(uuid.uuid4()),
            issue_key=f"retention-{uuid.uuid4().hex}",
            project_id=project.id,
            title="Old evidence",
            category="visual",
            severity="low",
            priority="P3",
            confidence_label="likely",
            confidence=0.7,
            status="new",
            url="https://shop.example.com/",
        )
        db.add(project)
        db.add(session)
        db.add(issue)
        await db.flush()
        evidence = IssueEvidence(
            id=str(uuid.uuid4()),
            issue_id=issue.id,
            session_id=session.id,
            kind="screenshot",
            path=str(tmp_path / session.id / "old.png"),
        )
        db.add(evidence)
        await db.commit()
        return session.id, issue.id


def test_retention_purges_old_evidence_and_marks_rows(tmp_path):
    session_id, _ = asyncio_run(_seed_retention(tmp_path))

    directory = tmp_path / session_id
    directory.mkdir(parents=True, exist_ok=True)
    old_file = directory / "old.png"
    old_file.write_bytes(b"\x89PNG\r\n\x1a\nfake")
    ancient = time.time() - 40 * 86400
    os.utime(old_file, (ancient, ancient))

    settings = get_settings()
    original_dir = settings.evidence_dir
    settings.evidence_dir = tmp_path
    try:
        store = LocalEvidenceStore(settings)

        async def run():
            async with SessionLocal() as db:
                return await purge_expired_evidence(db, store)

        result = asyncio_run(run())
    finally:
        settings.evidence_dir = original_dir

    assert result["removed_files"] >= 1
    assert result["purged_rows"] >= 1
    assert not old_file.exists()


def test_retention_keeps_fresh_evidence(tmp_path):
    session_id, _ = asyncio_run(_seed_retention(tmp_path))
    directory = tmp_path / session_id
    directory.mkdir(parents=True, exist_ok=True)
    fresh = directory / "fresh.png"
    fresh.write_bytes(b"\x89PNG\r\n\x1a\nfake")

    settings = get_settings()
    original_dir = settings.evidence_dir
    settings.evidence_dir = tmp_path
    try:
        store = LocalEvidenceStore(settings)

        async def run():
            async with SessionLocal() as db:
                return await purge_expired_evidence(db, store)

        result = asyncio_run(run())
    finally:
        settings.evidence_dir = original_dir

    assert fresh.exists()
    assert result["removed_files"] == 0


def test_purge_empty_dirs(tmp_path):
    (tmp_path / "empty-session").mkdir()
    (tmp_path / "kept").mkdir()
    (tmp_path / "kept" / "shot.png").write_bytes(b"x")
    removed = purge_empty_dirs(tmp_path)
    assert removed == 1
    assert not (tmp_path / "empty-session").exists()
    assert (tmp_path / "kept").exists()