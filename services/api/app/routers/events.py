"""Event endpoints.

The WebSocket lives next to the scan routes so the extension and the
dashboard share one protocol. The HTTP endpoint exposes the same history for
clients that cannot hold a socket open.
"""

from __future__ import annotations

from typing import Any

from bugpilot_core.events import EventBus
from fastapi import APIRouter, Depends

from app.deps import get_bus
from app.serializers import event_out

router = APIRouter(tags=["events"])


@router.get("/events/{session_id}")
async def event_history(
    session_id: str,
    bus: EventBus = Depends(get_bus),
) -> dict[str, Any]:
    events = [event_out(e) for e in await bus.history(session_id)]
    return {"items": events, "total": len(events)}
