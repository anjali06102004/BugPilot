"""Browser worker.

The worker owns the Playwright browser. It picks up queued scans from Redis
when it is available and always keeps a database poll as a fallback, so the
system works locally without extra infrastructure.

Reliability details:
- a scan is claimed with a conditional update, so two workers never run it twice
- scans left `running` by a crashed worker are returned to the queue on startup
- a heartbeat row lets `/api/v1/metrics` tell a dead worker from an idle queue
"""

from __future__ import annotations

import asyncio
import os
import signal
import socket
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update

from bugpilot_core.agent.runner import run_session
from bugpilot_core.config import get_settings
from bugpilot_core.db import SessionLocal, init_db
from bugpilot_core.db.models import TestSession, WorkerHeartbeat
from bugpilot_core.events import EventBus
from bugpilot_core.models import ScanStatus

settings = get_settings()
bus = EventBus(settings)

WORKER_ID = os.environ.get("BUGPILOT_WORKER_ID") or (
    f"{socket.gethostname()}-{os.getpid()}-{uuid.uuid4().hex[:6]}"
)

_shutdown = asyncio.Event()
_processed = 0


async def claim_session(session_id: str) -> bool:
    """Atomically move a queued scan to running. Returns False if another
    worker already claimed it."""
    async with SessionLocal() as db:
        result = await db.execute(
            update(TestSession)
            .where(TestSession.id == session_id, TestSession.status == ScanStatus.QUEUED.value)
            .values(status=ScanStatus.RUNNING.value, started_at=datetime.now(UTC))
        )
        await db.commit()
        return result.rowcount > 0


async def recover_stale_scans(minutes: int) -> int:
    """Return scans abandoned by a crashed worker to the queue."""
    if minutes <= 0:
        return 0
    cutoff = datetime.now(UTC) - timedelta(minutes=minutes)
    async with SessionLocal() as db:
        result = await db.execute(
            update(TestSession)
            .where(
                TestSession.status == ScanStatus.RUNNING.value,
                TestSession.started_at.isnot(None),
                TestSession.started_at < cutoff,
            )
            .values(
                status=ScanStatus.QUEUED.value,
                stop_reason="Recovered after worker restart",
            )
        )
        await db.commit()
        count = result.rowcount or 0
    if count:
        print(f"recovered {count} stale scan(s)", flush=True)
    return count


async def heartbeat(status: str) -> None:
    async with SessionLocal() as db:
        row = await db.get(WorkerHeartbeat, WORKER_ID)
        if row is None:
            row = WorkerHeartbeat(worker_id=WORKER_ID, status=status)
            db.add(row)
        row.status = status
        row.scans_processed = _processed
        row.event_transport = bus.transport
        row.last_seen_at = datetime.now(UTC)
        await db.commit()


async def process_session(session_id: str) -> None:
    global _processed
    async with SessionLocal() as db:
        await run_session(session_id, db, settings, bus)
    _processed += 1


async def poll_database() -> str | None:
    async with SessionLocal() as db:
        row = (
            await db.execute(
                select(TestSession)
                .where(TestSession.status == ScanStatus.QUEUED.value)
                .order_by(TestSession.created_at.asc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if not row:
            return None
        return row.id


async def worker_loop() -> None:
    await init_db()
    await bus.connect()
    _install_signal_handlers()
    recovered = await recover_stale_scans(settings.stale_scan_minutes)
    await heartbeat("idle")
    print(
        f"BugPilot browser worker listening for scans (event transport: {bus.transport})"
        + (f", recovered {recovered}" if recovered else ""),
        flush=True,
    )
    idle_ticks = 0
    while not _shutdown.is_set():
        session_id = await bus.dequeue_scan(timeout=1)
        if not session_id:
            session_id = await poll_database()
        if not session_id:
            idle_ticks += 1
            if idle_ticks % 15 == 0:
                await heartbeat("idle")
            try:
                await asyncio.wait_for(_shutdown.wait(), timeout=settings.worker_poll_seconds)
            except TimeoutError:
                pass
            continue
        idle_ticks = 0
        if not await claim_session(session_id):
            continue
        await heartbeat("running")
        try:
            await process_session(session_id)
        except Exception as exc:
            print(f"Scan {session_id} failed: {exc}", flush=True)
        finally:
            await heartbeat("idle")


def _install_signal_handlers() -> None:
    """Ask the running loop to stop on SIGINT/SIGTERM."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:  # pragma: no cover - no loop yet
        return
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _shutdown.set)
        except (NotImplementedError, AttributeError, RuntimeError):  # pragma: no cover - Windows
            pass


def run() -> None:
    if os.name == "nt":
        try:
            signal.signal(signal.SIGINT, lambda *_: _shutdown.set())
        except Exception:
            pass
    try:
        asyncio.run(worker_loop())
    except KeyboardInterrupt:  # pragma: no cover
        pass


if __name__ == "__main__":
    run()
