"""Phase 7 contracts: crash recovery for abandoned scans."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from bugpilot_core.db import SessionLocal, init_db
from bugpilot_core.db.models import Project, TestSession
from worker.main import claim_session, recover_stale_scans


async def _seed(status: str, started_minutes_ago: int | None) -> str:
    await init_db()
    async with SessionLocal() as db:
        project = Project(
            id=str(uuid.uuid4()),
            name="Recovery",
            website_url="https://shop.example.com/",
            environment="staging",
        )
        started = (
            datetime.now(UTC) - timedelta(minutes=started_minutes_ago)
            if started_minutes_ago is not None
            else None
        )
        session = TestSession(
            id=str(uuid.uuid4()),
            project_id=project.id,
            start_url="https://shop.example.com/",
            status=status,
            started_at=started,
        )
        db.add(project)
        db.add(session)
        await db.commit()
        return session.id


@pytest.mark.asyncio
async def test_stale_running_scan_is_requeued():
    stale_id = await _seed("running", 120)
    recovered = await recover_stale_scans(30)
    assert recovered >= 1

    async with SessionLocal() as db:
        row = await db.get(TestSession, stale_id)
        assert row.status == "queued"
        assert "Recovered" in (row.stop_reason or "")


@pytest.mark.asyncio
async def test_fresh_running_scan_is_left_alone():
    fresh_id = await _seed("running", 1)
    await recover_stale_scans(30)
    async with SessionLocal() as db:
        row = await db.get(TestSession, fresh_id)
        assert row.status == "running"


@pytest.mark.asyncio
async def test_disabled_recovery_is_a_noop():
    waiting_id = await _seed("running", 500)
    assert await recover_stale_scans(0) == 0
    async with SessionLocal() as db:
        row = await db.get(TestSession, waiting_id)
        assert row.status == "running"


@pytest.mark.asyncio
async def test_claim_is_atomic_and_only_once():
    queued_id = await _seed("queued", None)
    assert await claim_session(queued_id) is True
    assert await claim_session(queued_id) is False