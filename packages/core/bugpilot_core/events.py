"""Scan event transport.

Redis pub/sub carries live events when a Redis server is available. When it
is not, events are appended to the `scan_events` table instead, so the API and
the browser worker still share a single stream in local development. The
fallback is explicit: `EventBus.transport` reports which one is in use.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Any

from bugpilot_core.config import Settings
from bugpilot_core.models import ScanEvent

try:
    from redis.asyncio import Redis
except ImportError:  # pragma: no cover
    Redis = None  # type: ignore


class EventBus:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._redis: Any = None
        self._local: dict[str, list[ScanEvent]] = {}
        self._subscribers: dict[str, list[Callable[[ScanEvent], Awaitable[None]]]] = {}
        self._db_enabled = True

    # -- lifecycle -------------------------------------------------------
    async def connect(self) -> None:
        if Redis is None:
            return
        try:
            self._redis = Redis.from_url(self.settings.redis_url, decode_responses=True)
            await self._redis.ping()
        except Exception:
            self._redis = None

    async def close(self) -> None:
        if self._redis:
            await self._redis.close()

    @property
    def transport(self) -> str:
        return "redis" if self._redis else "database"

    def _channel(self, session_id: str) -> str:
        return f"{self.settings.event_channel_prefix}{session_id}"

    # -- publishing ------------------------------------------------------
    async def publish(self, event: ScanEvent) -> None:
        self._local.setdefault(event.session_id, []).append(event)
        for handler in list(self._subscribers.get(event.session_id, [])):
            try:
                await handler(event)
            except Exception:
                # A broken subscriber must never stop the scan.
                continue
        if self._redis:
            await self._redis.publish(self._channel(event.session_id), event.model_dump_json())
            await self._redis.rpush(f"{self._channel(event.session_id)}:log", event.model_dump_json())
        else:
            await self._persist(event)

    async def _persist(self, event: ScanEvent) -> None:
        if not self._db_enabled:
            return
        try:
            from bugpilot_core.db import SessionLocal
            from bugpilot_core.db.models import ScanEventRow

            async with SessionLocal() as db:
                db.add(
                    ScanEventRow(
                        session_id=event.session_id,
                        type=event.type,
                        message=event.message,
                        mascot=str(event.mascot),
                        payload=event.payload,
                    )
                )
                await db.commit()
        except Exception:
            self._db_enabled = False

    async def history(self, session_id: str) -> list[ScanEvent]:
        if self._redis:
            raw = await self._redis.lrange(f"{self._channel(session_id)}:log", 0, -1)
            return [ScanEvent.model_validate_json(item) for item in raw]
        stored = await self._history_from_db(session_id)
        if stored:
            return stored
        return list(self._local.get(session_id, []))

    async def _history_from_db(self, session_id: str) -> list[ScanEvent]:
        try:
            from sqlalchemy import select

            from bugpilot_core.db import SessionLocal
            from bugpilot_core.db.models import ScanEventRow

            async with SessionLocal() as db:
                rows = (
                    (
                        await db.execute(
                            select(ScanEventRow)
                            .where(ScanEventRow.session_id == session_id)
                            .order_by(ScanEventRow.id)
                        )
                    )
                    .scalars()
                    .all()
                )
            return [
                ScanEvent(
                    type=row.type,
                    session_id=row.session_id,
                    message=row.message,
                    mascot=row.mascot,
                    payload=row.payload or {},
                    timestamp=row.created_at,
                )
                for row in rows
            ]
        except Exception:
            return []

    # -- subscription ----------------------------------------------------
    def subscribe_local(self, session_id: str, handler: Callable[[ScanEvent], Awaitable[None]]) -> None:
        self._subscribers.setdefault(session_id, []).append(handler)

    def unsubscribe_local(self, session_id: str, handler: Callable[[ScanEvent], Awaitable[None]]) -> None:
        handlers = self._subscribers.get(session_id, [])
        if handler in handlers:
            handlers.remove(handler)

    # -- queue -----------------------------------------------------------
    async def enqueue_scan(self, session_id: str) -> bool:
        if not self._redis:
            return False
        await self._redis.rpush(self.settings.scan_queue_key, json.dumps({"session_id": session_id}))
        return True

    async def dequeue_scan(self, timeout: int = 5) -> str | None:
        if not self._redis:
            return None
        item = await self._redis.blpop(self.settings.scan_queue_key, timeout=timeout)
        if not item:
            return None
        payload = json.loads(item[1])
        return payload.get("session_id")
