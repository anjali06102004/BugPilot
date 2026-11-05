"""FastAPI application factory for the BugPilot API."""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from contextlib import asynccontextmanager

from bugpilot_core.config import get_settings
from bugpilot_core.db import init_db
from bugpilot_core.events import EventBus
from bugpilot_core.retention import purge_empty_dirs, purge_expired_evidence
from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import RateLimiter, auth_middleware, validate_production
from app.deps import build_evidence_store_once, get_db
from app.observability import collect_metrics, configure_logging
from app.routers import events, findings, issues, projects, reports, scans

settings = get_settings()
logger = logging.getLogger("bugpilot.api")
configure_logging(settings)


async def _retention_loop(app: FastAPI) -> None:
    """Purge expired evidence on a schedule. Disabled when the interval is 0."""
    interval = settings.retention_check_interval_seconds
    if interval <= 0:
        return
    while True:
        try:
            await asyncio.sleep(interval)
            async with app.state.session_factory() as db:
                result = await purge_expired_evidence(
                    db,
                    app.state.evidence_store,
                    default_retention_days=settings.evidence_retention_days,
                )
                purge_empty_dirs(settings.evidence_dir)
                if result["removed_files"]:
                    logger.info("evidence retention removed %s file(s)", result["removed_files"])
        except asyncio.CancelledError:
            return
        except Exception:
            logger.exception("evidence retention run failed")


@asynccontextmanager
async def lifespan(app: FastAPI):
    validate_production(settings)

    settings.evidence_dir.mkdir(parents=True, exist_ok=True)
    await init_db()
    bus = EventBus(settings)
    await bus.connect()
    from bugpilot_core.db import get_session_factory

    app.state.bus = bus
    app.state.evidence_store = build_evidence_store_once(settings)
    app.state.settings = settings
    app.state.rate_limiter = RateLimiter()
    app.state.session_factory = get_session_factory()
    app.state.started_at = time.time()
    retention_task = asyncio.create_task(_retention_loop(app))
    try:
        yield
    finally:
        retention_task.cancel()
        try:
            await retention_task
        except (asyncio.CancelledError, Exception):
            pass
        await bus.close()


app = FastAPI(
    title="BugPilot AI",
    version="0.3.0",
    description="Agentic UI testing, bug intelligence and browser experience platform.",
    lifespan=lifespan,
)

app.middleware("http")(auth_middleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def request_context(request: Request, call_next):
    request_id = request.headers.get("x-request-id") or uuid.uuid4().hex
    request.state.request_id = request_id
    started = time.perf_counter()
    response = await call_next(request)
    duration = round((time.perf_counter() - started) * 1000, 1)
    response.headers["x-request-id"] = request_id
    principal = getattr(request.state, "principal", None)
    if settings.log_json:
        logger.info(
            "request",
            extra={
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "status": response.status_code,
                "duration_ms": duration,
                "principal": principal.scope if principal else "anonymous",
            },
        )
    return response


@app.exception_handler(Exception)
async def unhandled_error(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={
            "error": {
                "code": "internal_error",
                "message": "An unexpected error occurred.",
                "details": {"request_id": getattr(request.state, "request_id", None)},
            }
        },
    )


@app.get("/health", tags=["system"])
async def health() -> dict:
    return {
        "ok": True,
        "service": "bugpilot-api",
        "version": app.version,
        "env": settings.bugpilot_env,
    }


@app.get("/api/v1/health", tags=["system"])
async def health_v1() -> dict:
    bus: EventBus = app.state.bus
    return {
        "ok": True,
        "service": "bugpilot-api",
        "version": app.version,
        "env": settings.bugpilot_env,
        "redis": bool(getattr(bus, "_redis", None)),
        "auth_required": settings.auth_required,
    }


@app.get("/api/v1/metrics", tags=["system"])
async def metrics(request: Request, db: AsyncSession = Depends(get_db)) -> dict:
    if not settings.metrics_enabled:
        return {"error": {"code": "disabled", "message": "Metrics are disabled."}}
    bus: EventBus = request.app.state.bus
    queue_depth = None
    try:
        if getattr(bus, "_redis", None):
            queue_depth = await bus._redis.llen(settings.scan_queue_key)
    except Exception:
        queue_depth = None
    return await collect_metrics(
        db,
        settings=settings,
        started_at=request.app.state.started_at,
        event_transport=bus.transport,
        queue_depth=queue_depth,
        version=app.version,
    )


for router in (
    projects.router,
    scans.router,
    findings.router,
    issues.router,
    reports.router,
    events.router,
):
    app.include_router(router, prefix=settings.api_prefix)


def run() -> None:
    import uvicorn

    uvicorn.run("app.main:app", host=settings.api_host, port=settings.api_port, reload=True)


if __name__ == "__main__":
    run()
