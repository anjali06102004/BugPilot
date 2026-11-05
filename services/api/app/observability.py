"""Metrics and structured logging.

The metrics endpoint is intentionally small and database-backed: it answers the
questions an operator actually asks during an incident (is the worker alive, is
the queue moving, what is the model latency, how many scans failed) without
requiring a metrics stack.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import UTC, datetime
from typing import Any

from bugpilot_core.config import Settings
from bugpilot_core.db.models import (
    Finding,
    Issue,
    ModelRun,
    TestSession,
    WorkerHeartbeat,
)
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key in ("request_id", "method", "path", "status", "duration_ms", "principal"):
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(settings: Settings) -> None:
    if not settings.log_json:
        return
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(logging.INFO)


async def collect_metrics(
    db: AsyncSession,
    *,
    settings: Settings,
    started_at: float,
    event_transport: str,
    queue_depth: int | None,
    version: str,
) -> dict[str, Any]:
    scans_by_status = dict(
        (
            await db.execute(
                select(TestSession.status, func.count(TestSession.id)).group_by(TestSession.status)
            )
        ).all()
    )
    issues_by_severity = dict(
        (await db.execute(select(Issue.severity, func.count(Issue.id)).group_by(Issue.severity))).all()
    )
    issues_by_status = dict(
        (await db.execute(select(Issue.status, func.count(Issue.id)).group_by(Issue.status))).all()
    )
    findings_total = (await db.execute(select(func.count(Finding.id)))).scalar_one()
    model_latency = (await db.execute(select(func.avg(ModelRun.latency_ms), func.count(ModelRun.id)))).one()
    tokens = (
        await db.execute(
            select(
                func.coalesce(func.sum(ModelRun.input_tokens), 0),
                func.coalesce(func.sum(ModelRun.output_tokens), 0),
            )
        )
    ).one()
    heartbeat = (
        await db.execute(select(WorkerHeartbeat).order_by(WorkerHeartbeat.last_seen_at.desc()).limit(1))
    ).scalar_one_or_none()

    heartbeat_age = None
    if heartbeat and heartbeat.last_seen_at:
        seen = heartbeat.last_seen_at
        if seen.tzinfo is None:
            seen = seen.replace(tzinfo=UTC)
        heartbeat_age = round((datetime.now(UTC) - seen).total_seconds(), 1)

    return {
        "version": version,
        "env": settings.bugpilot_env,
        "uptime_seconds": round(time.time() - started_at, 1),
        "event_transport": event_transport,
        "queue_depth": queue_depth,
        "worker": {
            "id": heartbeat.worker_id if heartbeat else None,
            "status": heartbeat.status if heartbeat else "unknown",
            "last_seen_seconds_ago": heartbeat_age,
            "scans_processed": heartbeat.scans_processed if heartbeat else 0,
            "healthy": heartbeat_age is not None and heartbeat_age < 120,
        },
        "scans": {"by_status": scans_by_status, "total": sum(scans_by_status.values())},
        "issues": {
            "by_severity": issues_by_severity,
            "by_status": issues_by_status,
            "total": sum(issues_by_status.values()),
        },
        "findings": {"total": findings_total},
        "model": {
            "runs": int(model_latency[1] or 0),
            "avg_latency_ms": round(float(model_latency[0] or 0), 1),
            "input_tokens": int(tokens[0] or 0),
            "output_tokens": int(tokens[1] or 0),
        },
    }
