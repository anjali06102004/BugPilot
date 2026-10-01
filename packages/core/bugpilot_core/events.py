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

    def _channel(self, session_id: str) -> str:
        return f"{self.settings.event_channel_prefix}{session_id}"

    async def publish(self, event: ScanEvent) -> None:
        self._local.setdefault(event.session_id, []).append(event)
        for handler in self._subscribers.get(event.session_id, []):
            await handler(event)
        if self._redis:
            await self._redis.publish(self._channel(event.session_id), event.model_dump_json())
            await self._redis.rpush(f"{self._channel(event.session_id)}:log", event.model_dump_json())

    async def history(self, session_id: str) -> list[ScanEvent]:
        if self._redis:
            raw = await self._redis.lrange(f"{self._channel(session_id)}:log", 0, -1)
            return [ScanEvent.model_validate_json(item) for item in raw]
        return list(self._local.get(session_id, []))

    def subscribe_local(self, session_id: str, handler: Callable[[ScanEvent], Awaitable[None]]) -> None:
        self._subscribers.setdefault(session_id, []).append(handler)

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
