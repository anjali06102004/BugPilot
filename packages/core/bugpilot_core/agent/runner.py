from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from bugpilot_core.agent.browser import BrowserSession
from bugpilot_core.agent.graph import RUNTIME, AgentRuntime, build_graph
from bugpilot_core.ai import build_provider
from bugpilot_core.config import Settings
from bugpilot_core.db.models import AgentRun, TestSession
from bugpilot_core.events import EventBus
from bugpilot_core.models import MascotState, ScanConfig, ScanEvent, ScanStatus
from bugpilot_core.policies.action_policy import ActionPolicy
from bugpilot_core.scope import ScopeGuard, build_scope_guard
from sqlalchemy.ext.asyncio import AsyncSession

STOP_SIGNALS = {ScanStatus.STOPPED.value, ScanStatus.CANCELLED.value}


async def run_session(
    session_id: str,
    db: AsyncSession,
    settings: Settings,
    bus: EventBus,
) -> None:
    record = await db.get(TestSession, session_id)
    if not record:
        return
    record.status = ScanStatus.RUNNING.value
    record.started_at = datetime.now(UTC)
    await db.commit()

    config = ScanConfig.model_validate(record.config_json or {})
    if record.scope_json:
        config = config.model_copy(update={"scope": config.scope.model_validate(record.scope_json)})
    scope = config.scope

    async def emit(event: ScanEvent) -> None:
        await bus.publish(event)

    browser = BrowserSession(
        session_id=session_id,
        config=config,
        evidence_dir=settings.evidence_dir,
        emit=emit,
    )
    guard: ScopeGuard = build_scope_guard(scope, record.start_url)
    token = None

    async def control() -> str:
        """Read the live scan status so pause/stop work while the agent runs."""
        current = await db.get(TestSession, session_id)
        if current is None:
            return "stop"
        status = current.status
        if status in STOP_SIGNALS:
            return "stop"
        if status == ScanStatus.PAUSED.value:
            return "pause"
        return "run"

    try:
        await browser.start()
        runtime = AgentRuntime(
            session=browser,
            db=db,
            settings=settings,
            ai=build_provider(settings),
            config=config,
            policy=ActionPolicy(
                allow_destructive=config.allow_destructive,
                environment=config.environment,
            ),
            started_at=datetime.now(UTC),
            snapshot_cache={},
            scope_guard=guard,
            session_row=record,
            control=control,
        )
        token = RUNTIME.set(runtime)
        db.add(
            AgentRun(
                id=str(uuid4()),
                session_id=session_id,
                status="running",
                graph_version="exploration_agent_v1",
            )
        )
        await db.commit()
        graph = build_graph()
        initial = {
            "session_id": session_id,
            "start_url": scope.start_url or record.start_url,
            "scope_type": scope.type.value,
            "config": config.model_dump(),
            "visited_urls": [],
            "tested_fingerprints": [],
            "action_history": [],
            "exploration_graph": {},
            "pending_actions": [],
            "current_url": scope.start_url or record.start_url,
            "current_viewport": config.viewports[0].model_dump(),
            "pages_visited": 0,
            "actions_taken": 0,
            "findings": [],
            "last_observation_summary": "",
            "suspicious": False,
            "should_stop": False,
            "stop_reason": "",
            "report_markdown": "",
            "skipped_pages": [],
        }
        await graph.ainvoke(initial, {"recursion_limit": 500})
        record = await db.get(TestSession, session_id)
        if record and record.status not in {
            ScanStatus.CANCELLED.value,
            ScanStatus.STOPPED.value,
            ScanStatus.FAILED.value,
        }:
            record.status = ScanStatus.COMPLETED.value
            record.completed_at = datetime.now(UTC)
            record.stop_reason = record.stop_reason or "Scan finished"
            await db.commit()
    except Exception as exc:
        # The failing transaction must be rolled back before the failure can be
        # recorded, otherwise the status update is lost too.
        await db.rollback()
        record = await db.get(TestSession, session_id)
        if record:
            record.status = ScanStatus.FAILED.value
            record.error_message = str(exc)
            record.completed_at = datetime.now(UTC)
            await db.commit()
        await bus.publish(
            ScanEvent(
                type="scan.completed",
                session_id=session_id,
                message="Scan interrupted. The browser worker stopped unexpectedly.",
                mascot=MascotState.ERROR,
                payload={"error": "worker_failure"},
            )
        )
        raise
    finally:
        if token is not None:
            RUNTIME.reset(token)
        await browser.close()
