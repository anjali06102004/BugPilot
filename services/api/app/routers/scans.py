from __future__ import annotations

import asyncio
import uuid
from datetime import UTC
from typing import Any

from bugpilot_core.config import Settings
from bugpilot_core.db.models import ActionRecord, Finding, PageRecord, Project, TestSession
from bugpilot_core.events import EventBus
from bugpilot_core.models import (
    CreateScanRequest,
    ScanScope,
    ScanStatus,
    ScopeType,
)
from bugpilot_core.security import TargetValidationError, validate_scan_target
from fastapi import APIRouter, Depends, Request, WebSocket, WebSocketDisconnect
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.access import assert_principal_project
from app.auth import principal_of
from app.deps import (
    ApiError,
    bad_request,
    get_bus,
    get_db,
    get_settings_dep,
    not_found,
    pagination,
)
from app.routers.findings import evidence_url_for
from app.serializers import action_out, event_out, finding_out, page_out, scan_out

router = APIRouter(tags=["scans"])


def _build_scope(body: CreateScanRequest, url: str) -> ScanScope:
    # The scope may arrive either at the top level or inside the config; the
    # top-level value wins because it is the explicit user choice.
    scope = (body.scope or body.config.scope).model_copy()
    scope.start_url = url
    if scope.type == ScopeType.SELECTED_ELEMENT and not scope.element_selector:
        raise bad_request("A selected element scan requires an element selector.")
    if scope.type == ScopeType.SINGLE_URL:
        scope.allowed_origins = [scope.origin() or url]
    if scope.type == ScopeType.FULL_SITE and not scope.allowed_origins:
        scope.allowed_origins = [scope.origin() or url]
    if scope.max_depth < 0:
        raise bad_request("max_depth cannot be negative.")
    return scope


@router.post("/scans")
async def create_scan(
    body: CreateScanRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings_dep),
    bus: EventBus = Depends(get_bus),
) -> dict[str, Any]:
    if body.idempotency_key:
        existing = (
            await db.execute(select(TestSession).where(TestSession.idempotency_key == body.idempotency_key))
        ).scalar_one_or_none()
        if existing:
            payload = scan_out(existing)
            payload["idempotent_replay"] = True
            return payload

    try:
        url = validate_scan_target(str(body.url), settings)
    except TargetValidationError as exc:
        raise bad_request(str(exc)) from exc

    scope = _build_scope(body, url)
    config = body.config.model_copy(update={"scope": scope})
    if body.environment == "production":
        config = config.model_copy(update={"allow_destructive": False, "environment": "production"})
    config = config.model_copy(
        update={
            "max_pages": min(config.max_pages, settings.max_pages_hard_limit),
            "max_duration_seconds": min(
                config.max_duration_seconds, settings.max_duration_seconds_hard_limit
            ),
            "max_actions": min(config.max_actions, settings.max_actions_hard_limit),
            "model_call_budget": min(config.model_call_budget, settings.max_model_calls_hard_limit),
            "environment": body.environment,
        }
    )

    principal = principal_of(request)
    if principal is not None and principal.project_id and not body.project_id:
        raise ApiError(
            403,
            "forbidden",
            "This API key is scoped to a project; pass project_id when creating a scan.",
        )

    project = None
    if body.project_id:
        project = await db.get(Project, body.project_id)
        if project is None:
            raise not_found("Project", body.project_id)
        assert_principal_project(principal, project.id)
    else:
        project = Project(
            id=str(uuid.uuid4()),
            name=body.project_name,
            website_url=url,
            environment=body.environment,
            description=body.description,
            critical_routes=config.critical_routes,
        )
        db.add(project)

    session = TestSession(
        id=str(uuid.uuid4()),
        project_id=project.id,
        start_url=url,
        status=ScanStatus.QUEUED.value,
        scope_type=scope.type.value,
        scope_json=scope.model_dump(),
        config_json=config.model_dump(),
        idempotency_key=body.idempotency_key,
    )
    db.add(session)
    await db.commit()

    queued = await bus.enqueue_scan(session.id)
    payload = scan_out(session)
    payload["queued_on_redis"] = queued
    return payload


@router.get("/scans")
async def list_scans(
    project_id: str | None = None,
    status: str | None = None,
    page=Depends(pagination),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    stmt = select(TestSession)
    count_stmt = select(func.count(TestSession.id))
    if project_id:
        stmt = stmt.where(TestSession.project_id == project_id)
        count_stmt = count_stmt.where(TestSession.project_id == project_id)
    if status:
        stmt = stmt.where(TestSession.status == status)
        count_stmt = count_stmt.where(TestSession.status == status)
    total = (await db.execute(count_stmt)).scalar_one()
    rows = (
        (await db.execute(stmt.order_by(TestSession.created_at.desc()).limit(page.limit).offset(page.offset)))
        .scalars()
        .all()
    )
    return {
        "items": [scan_out(s) for s in rows],
        "total": total,
        **page.as_dict(),
    }


@router.get("/scans/{scan_id}")
async def get_scan(
    scan_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    bus: EventBus = Depends(get_bus),
) -> dict[str, Any]:
    session = await db.get(TestSession, scan_id)
    if not session:
        raise not_found("Scan", scan_id)
    findings = (await db.execute(select(Finding).where(Finding.session_id == scan_id))).scalars().all()
    pages = (
        (
            await db.execute(
                select(PageRecord).where(PageRecord.session_id == scan_id).order_by(PageRecord.created_at)
            )
        )
        .scalars()
        .all()
    )
    actions = (
        (
            await db.execute(
                select(ActionRecord)
                .where(ActionRecord.session_id == scan_id)
                .order_by(ActionRecord.created_at)
            )
        )
        .scalars()
        .all()
    )
    events = [event_out(e) for e in await bus.history(scan_id)]
    config = session.config_json or {}
    payload = scan_out(session)
    payload["findings"] = [
        finding_out(f, evidence_url=evidence_url_for(request, f.screenshot_path)) for f in findings
    ]
    # Defensive de-duplication: older scans recorded one row per snapshot, so
    # collapse to the latest row per (url, viewport) when reading them back.
    latest_pages: dict[tuple[str, str], PageRecord] = {}
    for page_row in pages:
        latest_pages[(page_row.url, page_row.viewport_name)] = page_row
    payload["pages"] = [
        page_out(p, screenshot_url=evidence_url_for(request, p.screenshot_path))
        for p in latest_pages.values()
    ]
    payload["actions"] = [action_out(a) for a in actions]
    payload["budgets"] = {
        "pages": int(config.get("max_pages", 0) or 0),
        "actions": int(config.get("max_actions", 0) or 0),
        "duration_seconds": int(config.get("max_duration_seconds", 0) or 0),
        "model_calls": int(config.get("model_call_budget", 0) or 0),
    }
    payload["events"] = events
    return payload


@router.get("/scans/{scan_id}/findings")
async def scan_findings(scan_id: str, request: Request, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    rows = (await db.execute(select(Finding).where(Finding.session_id == scan_id))).scalars().all()
    return {
        "items": [finding_out(f, evidence_url=evidence_url_for(request, f.screenshot_path)) for f in rows],
        "total": len(rows),
    }


@router.get("/scans/{scan_id}/events")
async def scan_events(scan_id: str, bus: EventBus = Depends(get_bus)) -> dict[str, Any]:
    events = [event_out(e) for e in await bus.history(scan_id)]
    return {"items": events, "total": len(events)}


async def _set_status(
    session: TestSession,
    db: AsyncSession,
    status: str,
    *,
    stop_reason: str | None = None,
) -> None:
    session.status = status
    if stop_reason:
        session.stop_reason = stop_reason
    if status in {ScanStatus.STOPPED.value, ScanStatus.CANCELLED.value}:
        from datetime import datetime

        session.completed_at = datetime.now(UTC)
    await db.commit()


@router.post("/scans/{scan_id}/pause")
async def pause_scan(scan_id: str, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    session = await db.get(TestSession, scan_id)
    if not session:
        raise not_found("Scan", scan_id)
    if session.status not in {ScanStatus.RUNNING.value, ScanStatus.QUEUED.value}:
        raise ApiError(409, "invalid_state", f"A scan in state '{session.status}' cannot be paused.")
    await _set_status(session, db, ScanStatus.PAUSED.value)
    return scan_out(session)


@router.post("/scans/{scan_id}/resume")
async def resume_scan(scan_id: str, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    session = await db.get(TestSession, scan_id)
    if not session:
        raise not_found("Scan", scan_id)
    if session.status != ScanStatus.PAUSED.value:
        raise ApiError(409, "invalid_state", f"A scan in state '{session.status}' cannot be resumed.")
    await _set_status(session, db, ScanStatus.RUNNING.value)
    return scan_out(session)


@router.post("/scans/{scan_id}/stop")
async def stop_scan(scan_id: str, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    session = await db.get(TestSession, scan_id)
    if not session:
        raise not_found("Scan", scan_id)
    if session.status in {ScanStatus.COMPLETED.value, ScanStatus.FAILED.value}:
        raise ApiError(409, "invalid_state", f"A scan in state '{session.status}' is already finished.")
    await _set_status(session, db, ScanStatus.CANCELLED.value, stop_reason="Cancelled by user")
    return scan_out(session)


@router.websocket("/scans/{scan_id}/events")
async def scan_event_stream(websocket: WebSocket, scan_id: str) -> None:
    await websocket.accept()
    bus: EventBus = websocket.app.state.bus
    queue: list[dict[str, Any]] = []

    async def handler(event) -> None:
        queue.append(event.model_dump(mode="json"))

    bus.subscribe_local(scan_id, handler)
    sent = 0
    try:
        while True:
            try:
                history = await bus.history(scan_id)
            except Exception:
                history = []
            # Events published by the browser worker live in another process,
            # so the durable history is polled as well as the local queue.
            if len(history) > sent:
                for event in history[sent:]:
                    await websocket.send_json(event_out(event))
                sent = len(history)
            while queue:
                await websocket.send_json(queue.pop(0))
            try:
                await asyncio.wait_for(websocket.receive_text(), timeout=0.5)
            except TimeoutError:
                continue
            except WebSocketDisconnect:
                return
    except WebSocketDisconnect:
        return
    finally:
        bus.unsubscribe_local(scan_id, handler)
