from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from sqlalchemy import select

from bugpilot_core.agent.runner import run_session
from bugpilot_core.config import get_settings
from bugpilot_core.db import SessionLocal, init_db
from bugpilot_core.db.models import TestSession
from bugpilot_core.events import EventBus
from bugpilot_core.models import ScanStatus

settings = get_settings()
bus = EventBus(settings)


async def process_session(session_id: str) -> None:
    async with SessionLocal() as db:
        await run_session(session_id, db, settings, bus)


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
    print("BugPilot browser worker listening for scans")
    while True:
        session_id = await bus.dequeue_scan(timeout=3)
        if not session_id:
            session_id = await poll_database()
        if not session_id:
            await asyncio.sleep(1)
            continue
        try:
            await process_session(session_id)
        except Exception as exc:
            print(f"Scan {session_id} failed: {exc}")


def run() -> None:
    asyncio.run(worker_loop())


if __name__ == "__main__":
    run()
