from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse
from uuid import uuid4

from bugpilot_core.agent.browser import BrowserSession
from bugpilot_core.agent.state import AgentState
from bugpilot_core.ai.prompts import REASONING_PROMPT_V1, VISION_PROMPT_V1
from bugpilot_core.ai.providers.base import AIProvider, VisionAnalysis
from bugpilot_core.config import Settings
from bugpilot_core.db.models import (
    ActionRecord,
    Finding,
    FindingEvidence,
    Issue,
    ModelRun,
    Observation,
    PageRecord,
    TestSession,
    VerificationRun,
)
from bugpilot_core.dedupe import dedupe_candidates
from bugpilot_core.detectors import run_detectors
from bugpilot_core.models import (
    ActionType,
    ConfidenceLabel,
    DomElement,
    FindingCandidate,
    FindingCategory,
    FindingStatus,
    InteractionDepth,
    MascotState,
    PlannedAction,
    ScanConfig,
    ScanEvent,
    ScopeType,
    TestCategory,
    Viewport,
)
from bugpilot_core.policies.action_policy import ActionPolicy
from bugpilot_core.registry import record_occurrence
from bugpilot_core.scope import ScopeGuard
from bugpilot_core.scoring.actions import score_action
from bugpilot_core.severity import PrioritySignals, score_priority, score_severity
from langgraph.graph import END, START, StateGraph
from sqlalchemy.ext.asyncio import AsyncSession

RUNTIME: ContextVar[AgentRuntime] = ContextVar("bugpilot_runtime")

ControlSignal = Callable[[], Awaitable[str]]


@dataclass
class AgentRuntime:
    session: BrowserSession
    db: AsyncSession
    settings: Settings
    ai: AIProvider
    config: ScanConfig
    policy: ActionPolicy
    started_at: datetime
    snapshot_cache: dict[str, Any]
    scope_guard: ScopeGuard
    session_row: TestSession
    control: ControlSignal | None = None
    model_calls: int = 0
    page_records: dict[tuple[str, str], PageRecord] = field(default_factory=dict)
    extra: dict[str, Any] = field(default_factory=dict)


def runtime() -> AgentRuntime:
    return RUNTIME.get()


async def emit(event_type: str, message: str, mascot: MascotState, payload: dict | None = None) -> None:
    rt = runtime()
    await rt.session.emit(
        ScanEvent(
            type=event_type,
            session_id=rt.session.session_id,
            message=message,
            mascot=mascot,
            payload=payload or {},
        )
    )


async def _await_resume(rt: AgentRuntime) -> str:
    """Block while the scan is paused.

    Returns 'stop' when the scan was cancelled while paused, otherwise 'run'.
    """
    await emit("scan.paused", "Scan paused — waiting for resume", MascotState.PAUSED)
    while True:
        await asyncio.sleep(1.0)
        signal = await rt.control() if rt.control else "run"
        if signal == "stop":
            return "stop"
        if signal == "run":
            await emit("scan.resumed", "Scan resumed", MascotState.EXPLORING)
            return "run"


async def _check_control(rt: AgentRuntime) -> str:
    if not rt.control:
        return "run"
    return await rt.control()


async def initialize(state: AgentState) -> AgentState:
    rt = runtime()
    await emit(
        "scan.started",
        "🐞 Starting scan",
        MascotState.WAKING,
        {"scope": rt.config.scope.type.value, "start_url": rt.config.scope.start_url},
    )
    start_url = rt.config.scope.start_url or state["start_url"]
    await rt.session.goto(start_url)
    state["current_url"] = rt.session.page.url if rt.session.page else start_url
    state["visited_urls"] = [state["current_url"]]
    state["current_viewport"] = rt.config.viewports[0].model_dump()
    state["exploration_graph"] = {state["current_url"]: []}
    return state


async def analyze_page(state: AgentState) -> AgentState:
    rt = runtime()
    viewport = Viewport.model_validate(state["current_viewport"])
    snap = await rt.session.snapshot(viewport)
    rt.snapshot_cache["current"] = snap
    interactive = [el for el in snap.elements if el.interactive and el.visible]
    await emit(
        "page.loaded",
        f"Opened {snap.title or snap.url} — discovered {len(interactive)} interactive elements",
        MascotState.EXPLORING,
        {
            "url": snap.url,
            "screenshot": f"/evidence/{state['session_id']}/{Path(snap.screenshot_path).name}"
            if snap.screenshot_path
            else None,
            "title": snap.title,
            "viewport": viewport.model_dump(),
        },
    )
    # One `pages` row per (url, viewport). Every snapshot is still recorded as
    # an observation, but a page is a page, not one row per interaction.
    page_key = (snap.url, viewport.name)
    existing_page = rt.page_records.get(page_key)
    if existing_page is not None:
        existing_page.screenshot_path = snap.screenshot_path
        existing_page.title = snap.title or existing_page.title
    else:
        page = PageRecord(
            id=str(uuid4()),
            session_id=state["session_id"],
            url=snap.url,
            title=snap.title,
            viewport_name=viewport.name,
            screenshot_path=snap.screenshot_path,
        )
        rt.db.add(page)
        rt.page_records[page_key] = page
    rt.db.add(
        Observation(
            id=str(uuid4()),
            session_id=state["session_id"],
            url=snap.url,
            summary=f"{len(snap.elements)} elements, {len(interactive)} interactive",
            payload={"title": snap.title, "viewport": viewport.model_dump()},
        )
    )
    await rt.db.commit()
    state["current_url"] = snap.url
    state["current_screenshot"] = snap.screenshot_path or ""
    state["last_observation_summary"] = f"{snap.title}: {len(interactive)} interactive elements"
    if snap.url not in state["visited_urls"]:
        state["visited_urls"] = [*state["visited_urls"], snap.url]
    state["pages_visited"] = len(state["visited_urls"])
    return state


def _scope_allows_element(rt: AgentRuntime, el: DomElement) -> bool:
    """Selected element scans only inspect the chosen region and its children."""
    scope = rt.config.scope
    if scope.type != ScopeType.SELECTED_ELEMENT:
        return True
    root = scope.element_selector
    if not root:
        return True
    if el.selector == root:
        return True
    return el.selector.startswith(root + " > ") or el.selector.startswith(root + " ")


def _plan_from_snapshot(state: AgentState) -> list[PlannedAction]:
    rt = runtime()
    snap = rt.snapshot_cache["current"]
    seen = set(state["tested_fingerprints"])
    visited = set(state["visited_urls"])
    actions: list[PlannedAction] = []
    origin = urlparse(state["start_url"]).netloc
    scope = rt.config.scope
    single_url = scope.type == ScopeType.SINGLE_URL
    element_scope = scope.type == ScopeType.SELECTED_ELEMENT
    allow_interaction = scope.interaction_depth != InteractionDepth.NONE
    # The page budget bounds how many distinct pages are opened. It must not
    # stop interactions on a page that is already open, otherwise a single-URL
    # scan with max_pages=1 would never test anything.
    pages_exhausted = state["pages_visited"] >= rt.config.max_pages

    for el in snap.elements:
        if not el.visible:
            continue
        if element_scope and not _scope_allows_element(rt, el):
            continue
        if el.interactive and (el.tag in {"a", "button"} or el.role in {"link", "button"}):
            href = el.href or ""
            abs_url = urljoin(snap.url, href) if href else None
            action_type = ActionType.NAVIGATE if abs_url and href else ActionType.CLICK
            if single_url and action_type == ActionType.NAVIGATE:
                # A single URL scan inspects the page it was given; it does not
                # follow the page's own links.
                action_type = ActionType.CLICK
            if (single_url or element_scope) and el.attributes.get("type") == "submit":
                # Submitting a form leaves the page, which these scopes forbid.
                continue
            if pages_exhausted and action_type == ActionType.NAVIGATE:
                # No budget left to open another page.
                continue
            if abs_url and urlparse(abs_url).netloc != origin:
                continue
            planned = PlannedAction(
                type=action_type,
                selector=el.selector,
                fingerprint=el.fingerprint,
                url=abs_url,
                description=f"{action_type.value} {el.text or el.selector}",
            )
            planned = rt.policy.evaluate(planned, el.text, href)
            actions.append(score_action(planned, el, seen_fingerprints=seen, visited_urls=visited))
        if (
            el.tag in {"input", "textarea"}
            and el.attributes.get("type") not in {"hidden", "submit"}
            and allow_interaction
        ):
            planned = PlannedAction(
                type=ActionType.FILL,
                selector=el.selector,
                fingerprint=el.fingerprint,
                value="test@example.com" if "email" in (el.type or el.name or "") else "BugPilot sample",
                description=f"fill {el.selector}",
            )
            planned = rt.policy.evaluate(planned, el.text, "")
            actions.append(score_action(planned, el, seen_fingerprints=seen, visited_urls=visited))

    if allow_interaction and not element_scope:
        planned = PlannedAction(type=ActionType.SCROLL, description="Scroll the page", selector="body")
        actions.append(score_action(planned, None, seen_fingerprints=seen, visited_urls=visited))
    if TestCategory.RESPONSIVE in rt.config.categories:
        for vp in rt.config.viewports[1:]:
            planned = PlannedAction(
                type=ActionType.RESIZE,
                description=f"Resize to {vp.name} {vp.width}x{vp.height}",
                value=json.dumps(vp.model_dump()),
                fingerprint=f"resize:{vp.name}",
            )
            actions.append(score_action(planned, None, seen_fingerprints=seen, visited_urls=visited))

    # The scope is a hard boundary: anything the guard rejects never reaches
    # the browser.
    allowed: list[PlannedAction] = []
    for action in actions:
        if action.blocked_by_policy:
            continue
        decision = rt.scope_guard.check_action(action, state["current_url"])
        if not decision.allowed:
            continue
        allowed.append(action)
    allowed.sort(key=lambda a: a.score, reverse=True)

    limit = 12
    if scope.type == ScopeType.SINGLE_URL:
        limit = 6
    elif scope.type == ScopeType.SELECTED_ELEMENT:
        limit = 4
    return allowed[:limit]


async def discover_elements(state: AgentState) -> AgentState:
    actions = _plan_from_snapshot(state)
    await emit(
        "action.planned",
        f"Planning {len(actions)} candidate actions",
        MascotState.EXPLORING,
        {"actions": [a.model_dump() for a in actions]},
    )
    state["pending_actions"] = [a.model_dump() for a in actions]
    return state


async def plan_action(state: AgentState) -> AgentState:
    if not state["pending_actions"]:
        state["pending_actions"] = [a.model_dump() for a in _plan_from_snapshot(state)]
    return state


async def execute_action(state: AgentState) -> AgentState:
    rt = runtime()
    signal = await _check_control(rt)
    if signal == "pause":
        if await _await_resume(rt) == "stop":
            state["should_stop"] = True
            state["stop_reason"] = "Scan cancelled by user"
            return state
    elif signal == "stop":
        state["should_stop"] = True
        state["stop_reason"] = "Scan cancelled by user"
        return state

    pending = list(state["pending_actions"])
    if not pending:
        return state
    action = PlannedAction.model_validate(pending.pop(0))
    state["pending_actions"] = pending
    if action.fingerprint:
        state["tested_fingerprints"] = [*state["tested_fingerprints"], action.fingerprint]

    # Re-check the scope immediately before the action, using the live URL.
    decision = rt.scope_guard.check_action(action, state["current_url"])
    if not decision.allowed:
        await emit(
            "action.blocked",
            f"Skipped '{action.description}' — {decision.reason}",
            MascotState.IDLE,
            {"action": action.model_dump(), "reason": decision.reason},
        )
        rt.db.add(
            ActionRecord(
                id=str(uuid4()),
                session_id=state["session_id"],
                type=action.type.value,
                description=action.description,
                selector=action.selector,
                url=action.url,
                blocked=1,
                block_reason=decision.reason,
            )
        )
        await rt.db.commit()
        return state

    await emit(
        "action.started",
        f"🐞 {action.description}",
        MascotState.EXPLORING,
        {"action": action.model_dump()},
    )
    try:
        if action.type == ActionType.CLICK and action.selector:
            previous = state["current_url"]
            await rt.session.click(action.selector)
            new_url = rt.session.page.url if rt.session.page else previous
            if new_url != previous:
                # A click can navigate through a form submit or a script even
                # when the element itself has no href. If it left the scope,
                # return to the page the user authorised.
                decision = rt.scope_guard.check_navigation(previous, new_url)
                if not decision.allowed:
                    await rt.session.goto(previous)
                    state["current_url"] = previous
                    await emit(
                        "action.blocked",
                        f"Restored {previous} — {decision.reason}",
                        MascotState.IDLE,
                        {"reason": decision.reason, "blocked_url": new_url},
                    )
                else:
                    rt.scope_guard.note_navigation(previous, new_url)
        elif action.type == ActionType.NAVIGATE and action.selector:
            previous = state["current_url"]
            await rt.session.click(action.selector)
            new_url = rt.session.page.url if rt.session.page else previous
            navigation = rt.scope_guard.check_navigation(previous, new_url)
            if not navigation.allowed:
                # The click led somewhere the scope forbids: go back.
                await rt.session.goto(previous)
                new_url = previous
            else:
                rt.scope_guard.note_navigation(previous, new_url)
            graph = dict(state["exploration_graph"])
            graph.setdefault(previous, []).append(new_url)
            graph.setdefault(new_url, [])
            state["exploration_graph"] = graph
        elif action.type == ActionType.FILL and action.selector:
            await rt.session.fill(action.selector, action.value or "sample")
        elif action.type == ActionType.HOVER and action.selector:
            await rt.session.hover(action.selector)
        elif action.type == ActionType.SCROLL:
            await rt.session.scroll()
        elif action.type == ActionType.RESIZE and action.value:
            vp = Viewport.model_validate(json.loads(action.value))
            await rt.session.resize(vp)
            state["current_viewport"] = vp.model_dump()
        rt.db.add(
            ActionRecord(
                id=str(uuid4()),
                session_id=state["session_id"],
                type=action.type.value,
                description=action.description,
                selector=action.selector,
                url=action.url,
            )
        )
        await rt.db.commit()
        state["actions_taken"] = state["actions_taken"] + 1
        # Keep a bounded, structured trace so a fix can be verified later by
        # replaying the same actions, not by guessing from prose steps.
        state["action_history"] = [
            *state.get("action_history", []),
            {
                "type": action.type.value,
                "selector": action.selector,
                "value": action.value,
                "url": action.url,
            },
        ][-20:]
        await emit("action.completed", f"Completed: {action.description}", MascotState.EXPLORING)
    except Exception as exc:
        await emit(
            "action.completed",
            f"Action failed (recovered): {action.description}",
            MascotState.ERROR,
            {"error": str(exc)},
        )
    return state


async def observe(state: AgentState) -> AgentState:
    return await analyze_page(state)


async def run_detector_node(state: AgentState) -> AgentState:
    rt = runtime()
    snap = rt.snapshot_cache["current"]
    previous = state["visited_urls"][-2] if len(state["visited_urls"]) > 1 else None
    raw = run_detectors(snap, rt.config.categories, previous_url=previous)
    merged = dedupe_candidates(raw)
    if merged:
        await emit(
            "detector.triggered",
            f"⚠ {len(merged)} suspicious signal(s)",
            MascotState.SUSPICIOUS,
            {"count": len(merged), "titles": [c.title for c in merged[:5]]},
        )
        state["suspicious"] = True
    else:
        state["suspicious"] = False
    existing = [FindingCandidate.model_validate(f) for f in state["findings"]]
    combined = dedupe_candidates(existing + merged)
    state["findings"] = [c.model_dump() for c in combined]
    return state


async def analyze_suspicious(state: AgentState) -> AgentState:
    rt = runtime()
    if not state["suspicious"]:
        return state
    if rt.model_calls >= rt.config.model_call_budget:
        await emit(
            "detector.skipped",
            "Model call budget reached — skipping visual analysis",
            MascotState.IDLE,
        )
        return state
    snap = rt.snapshot_cache["current"]
    image_bytes = b""
    if snap.screenshot_path:
        image_bytes = Path(snap.screenshot_path).read_bytes()
    context = {
        "url": snap.url,
        "viewport": snap.viewport.model_dump(),
        "recent_action": rt.session.last_action,
        "console": [e.model_dump(mode="json") for e in snap.console[-8:]],
        "network": [e.model_dump(mode="json") for e in snap.network[-8:]],
        "dom_summary": [
            {
                "tag": el.tag,
                "text": el.text,
                "selector": el.selector,
                "box": el.box.model_dump() if el.box else None,
            }
            for el in snap.elements
            if el.interactive
        ][:40],
        "previous_observation": state["last_observation_summary"],
        "detector_findings": state["findings"][-5:],
    }
    started = datetime.now(UTC)
    analysis: VisionAnalysis = await rt.ai.analyze_vision(
        prompt=VISION_PROMPT_V1, image_bytes=image_bytes, context=context
    )
    rt.model_calls += 1
    latency = int((datetime.now(UTC) - started).total_seconds() * 1000)
    rt.db.add(
        ModelRun(
            id=str(uuid4()),
            session_id=state["session_id"],
            prompt_name="vision_detector",
            prompt_version="v1",
            provider=rt.ai.capabilities().name,
            model=rt.settings.gemini_model
            if rt.settings.ai_provider == "gemini"
            else rt.settings.openai_model,
            latency_ms=latency,
        )
    )
    await rt.db.commit()
    extra: list[FindingCandidate] = []
    for anomaly in analysis.anomalies:
        extra.append(
            FindingCandidate(
                category=FindingCategory.VISUAL,
                title=anomaly.title,
                description=anomaly.description,
                confidence=anomaly.confidence,
                source="ai_reasoning",
                selector=anomaly.selector_hint,
                url=snap.url,
                viewport=snap.viewport,
                expected=anomaly.expected,
                actual=anomaly.actual,
                metadata={"ai_hypothesis": True},
            )
        )
    if extra:
        combined = dedupe_candidates([FindingCandidate.model_validate(f) for f in state["findings"]] + extra)
        state["findings"] = [c.model_dump() for c in combined]
    await emit("detector.triggered", "🔍 Running visual analysis", MascotState.INSPECTING)
    return state


async def collect_evidence(state: AgentState) -> AgentState:
    """Attach the page screenshot and viewport to every candidate found here."""
    rt = runtime()
    snap = rt.snapshot_cache.get("current")
    if not snap:
        return state
    updated: list[dict[str, Any]] = []
    for raw in state["findings"]:
        candidate = FindingCandidate.model_validate(raw)
        if not any(e.kind == "screenshot" for e in candidate.evidence):
            if snap.screenshot_path:
                candidate.evidence.append(_screenshot_evidence(snap.screenshot_path))
        if not any(e.kind == "timestamp" for e in candidate.evidence):
            candidate.evidence.append(_timestamp_evidence())
        updated.append(candidate.model_dump())
    state["findings"] = updated
    return state


def _screenshot_evidence(path: str):
    from bugpilot_core.models import EvidenceItem

    return EvidenceItem(kind="screenshot", path=path)


def _timestamp_evidence():
    from bugpilot_core.models import EvidenceItem

    return EvidenceItem(kind="timestamp", content={"at": datetime.now(UTC).isoformat()})


async def verify_findings(state: AgentState) -> AgentState:
    rt = runtime()
    snap = rt.snapshot_cache["current"]
    verified: list[FindingCandidate] = []
    unverified = 0
    for raw in state["findings"]:
        candidate = FindingCandidate.model_validate(raw)
        if candidate.metadata.get("reproduced") is not None:
            verified.append(candidate)
            continue
        if unverified >= 8:
            verified.append(candidate)
            continue
        unverified += 1
        if rt.model_calls >= rt.config.model_call_budget:
            candidate.metadata.setdefault("confidence_label", "possible")
            verified.append(candidate)
            continue
        started = datetime.now(UTC)
        reasoning = await rt.ai.reason(
            prompt=REASONING_PROMPT_V1,
            context={"candidate": candidate.model_dump(mode="json"), "url": snap.url},
        )
        rt.model_calls += 1
        rt.db.add(
            ModelRun(
                id=str(uuid4()),
                session_id=state["session_id"],
                prompt_name="reasoning_agent",
                prompt_version="v1",
                provider=rt.ai.capabilities().name,
                model=rt.settings.gemini_model,
                latency_ms=int((datetime.now(UTC) - started).total_seconds() * 1000),
            )
        )
        reproduced = False
        if reasoning.should_verify or candidate.confidence >= 0.75:
            await emit("verification.started", f"Verifying: {candidate.title}", MascotState.VERIFYING)
            again = await rt.session.snapshot(Viewport.model_validate(state["current_viewport"]))
            rt.snapshot_cache["verify"] = again
            second = run_detectors(again, rt.config.categories)
            reproduced = any(
                c.error_signature == candidate.error_signature
                or (c.title == candidate.title and c.category == candidate.category)
                for c in second
            )
        label = reasoning.label.lower()
        if reproduced and label in {"confirmed", "likely", "possible"}:
            label = "confirmed" if reproduced else label
        candidate.metadata["confidence_label"] = label
        candidate.metadata["reproduced"] = reproduced
        candidate.metadata["root_cause"] = reasoning.root_cause
        candidate.metadata["suggested_fix"] = reasoning.suggested_fix
        candidate.steps = reasoning.reproduction_steps or candidate.steps
        if reasoning.what_should_happen:
            candidate.expected = candidate.expected or reasoning.what_should_happen
        if reasoning.what_happened:
            candidate.actual = candidate.actual or reasoning.what_happened
        verified.append(candidate)
        if reproduced:
            await emit(
                "verification.completed",
                f"🐞 Bug confirmed: {candidate.title}",
                MascotState.BUG_FOUND,
                {"title": candidate.title},
            )
    state["findings"] = [c.model_dump() for c in verified]
    await persist_findings(state)
    return state


def _is_critical_route(rt: AgentRuntime, route: str | None) -> bool:
    if not route:
        return False
    for pattern in rt.config.critical_routes:
        if pattern and (pattern in route):
            return True
    return False


async def persist_findings(state: AgentState) -> None:
    rt = runtime()
    from sqlalchemy import select

    rows = (
        (await rt.db.execute(select(Finding).where(Finding.session_id == state["session_id"])))
        .scalars()
        .all()
    )
    by_sig = {(f.category, f.title, f.url): f for f in rows}

    for raw in state["findings"]:
        candidate = FindingCandidate.model_validate(raw)
        reproduced = bool(candidate.metadata.get("reproduced"))
        label = candidate.metadata.get("confidence_label") or "likely"
        try:
            conf_label = ConfidenceLabel(label)
        except ValueError:
            conf_label = ConfidenceLabel.LIKELY
        if conf_label == ConfidenceLabel.NOT_A_BUG:
            status = FindingStatus.NOT_A_BUG
        elif reproduced and conf_label == ConfidenceLabel.CONFIRMED:
            status = FindingStatus.VERIFIED
        else:
            status = FindingStatus.NEW

        severity = score_severity(candidate, reproduced=reproduced)
        route = candidate.route or _route_of(candidate.url)
        priority_result = score_priority(
            candidate,
            PrioritySignals(
                severity=severity,
                confidence=conf_label,
                blocks_critical_flow=float(candidate.metadata.get("workflow_impact", 0)) >= 0.8,
                on_critical_route=_is_critical_route(rt, route),
                regression=candidate.regression,
                occurrence_count=int(candidate.metadata.get("occurrence_count", 1)),
                affected_pages=int(candidate.metadata.get("affected_pages", 1)),
                data_risk=float(candidate.metadata.get("data_impact", 0)) > 0,
                accessibility=candidate.category == FindingCategory.ACCESSIBILITY,
                workaround_exists=bool(candidate.metadata.get("workaround_exists", True)),
                user_reachable=bool(candidate.metadata.get("user_reachable", True)),
            ),
        )
        priority = priority_result.priority
        candidate.metadata["priority_rationale"] = priority_result.rationale
        # Structured reproduction data, used later by fix verification.
        candidate.metadata["reproduction"] = {
            "url": candidate.url,
            "viewport": candidate.viewport.model_dump() if candidate.viewport else None,
            "selector": candidate.selector,
            "error_signature": candidate.error_signature,
            "actions": list(state.get("action_history", [])),
        }

        key = (candidate.category.value, candidate.title, candidate.url)
        finding = by_sig.get(key)
        if not finding:
            finding = Finding(
                id=str(uuid4()),
                session_id=state["session_id"],
                category=candidate.category.value,
                title=candidate.title,
                description=candidate.description,
                severity=severity.value,
                priority=priority.value,
                confidence=candidate.confidence,
                confidence_label=conf_label.value,
                status=status.value,
                source=candidate.source,
                url=candidate.url,
                route=route,
                component=candidate.component,
                selector=candidate.selector,
                fingerprint=candidate.fingerprint,
                expected=candidate.expected,
                actual=candidate.actual,
                steps_json=candidate.steps,
                suggested_fix=candidate.metadata.get("suggested_fix"),
                root_cause=candidate.metadata.get("root_cause"),
                reproduced_count=1 if reproduced else 0,
                verification_attempts=1,
                screenshot_path=_first_screenshot(candidate),
                extra={
                    **candidate.metadata,
                    "priority_rationale": priority_result.rationale,
                    "reproduced": reproduced,
                    "viewport": candidate.viewport.name if candidate.viewport else None,
                    "root_cause": candidate.metadata.get("root_cause"),
                },
            )
            rt.db.add(finding)
            by_sig[key] = finding
            for item in candidate.evidence:
                rt.db.add(
                    FindingEvidence(
                        id=str(uuid4()),
                        finding_id=finding.id,
                        kind=item.kind,
                        path=item.path,
                        content=item.content if isinstance(item.content, dict) else {"value": item.content},
                    )
                )
            rt.db.add(
                VerificationRun(
                    id=str(uuid4()),
                    finding_id=finding.id,
                    reproduced=1 if reproduced else 0,
                    notes=f"{finding.reproduced_count}/{finding.verification_attempts}",
                )
            )
            await rt.db.flush()
            issue, created, regression = await record_occurrence(
                rt.db,
                session=rt.session_row,
                finding=finding,
                candidate=candidate,
                severity=severity.value,
                priority=priority.value,
                confidence_label=conf_label.value,
                confidence=candidate.confidence,
                environment=rt.config.environment,
                browser=rt.config.browser.value,
                viewport=candidate.viewport.name if candidate.viewport else None,
            )
            finding.issue_id = issue.id
            await emit(
                "finding.created",
                f"Finding: {candidate.title}",
                MascotState.BUG_FOUND if status == FindingStatus.VERIFIED else MascotState.SUSPICIOUS,
                {
                    "finding_id": finding.id,
                    "issue_id": issue.id,
                    "title": candidate.title,
                    "severity": severity.value,
                    "priority": priority.value,
                    "status": status.value,
                    "regression": regression,
                },
            )
        else:
            finding.verification_attempts += 1
            if reproduced:
                finding.reproduced_count += 1
                finding.status = FindingStatus.VERIFIED.value
                finding.confidence_label = ConfidenceLabel.CONFIRMED.value
            # Findings first appear before any interaction; once we have real
            # actions, keep the longest reproduction trace for fix verification.
            reproduction = candidate.metadata.get("reproduction") or {}
            existing = (finding.extra or {}).get("reproduction") or {}
            if len(reproduction.get("actions") or []) > len(existing.get("actions") or []):
                finding.extra = {**(finding.extra or {}), "reproduction": reproduction}
                issue = await rt.db.get(Issue, finding.issue_id) if finding.issue_id else None
                if issue is not None:
                    issue.extra = {**(issue.extra or {}), "reproduction": reproduction}
    await rt.db.commit()


def _route_of(url: str) -> str:
    from urllib.parse import urlparse

    return urlparse(url).path or "/"


def _first_screenshot(candidate: FindingCandidate) -> str | None:
    for item in candidate.evidence:
        if item.kind in {"screenshot", "highlighted_screenshot"} and item.path:
            return item.path
    return None


async def update_state(state: AgentState) -> AgentState:
    rt = runtime()
    signal = await _check_control(rt)
    if signal == "pause":
        if await _await_resume(rt) == "stop":
            state["should_stop"] = True
            state["stop_reason"] = "Scan cancelled by user"
            return state
    elif signal == "stop":
        state["should_stop"] = True
        state["stop_reason"] = "Scan cancelled by user"
        return state

    elapsed = (datetime.now(UTC) - rt.started_at).total_seconds()
    if elapsed >= rt.config.max_duration_seconds:
        state["should_stop"] = True
        state["stop_reason"] = "Scan duration budget reached"
    elif state["actions_taken"] >= rt.config.max_actions:
        state["should_stop"] = True
        state["stop_reason"] = "Action budget reached"
    elif not state["pending_actions"]:
        refreshed = _plan_from_snapshot(state)
        unused = [a for a in refreshed if a.fingerprint not in set(state["tested_fingerprints"])]
        if unused:
            state["pending_actions"] = [a.model_dump() for a in unused[:8]]
        elif state["pages_visited"] >= rt.config.max_pages:
            state["should_stop"] = True
            state["stop_reason"] = "Page budget reached"
        else:
            state["should_stop"] = True
            state["stop_reason"] = "No new states to explore"

    if state["should_stop"]:
        skipped = rt.scope_guard.skipped
        if skipped:
            state["skipped_pages"] = [{"url": u, "reason": r} for u, r in skipped]
    session = await rt.db.get(TestSession, state["session_id"])
    if session:
        session.pages_tested = state["pages_visited"]
        session.actions_taken = state["actions_taken"]
        session.model_calls = rt.model_calls
        session.pages_skipped = len(rt.scope_guard.skipped)
        if state["should_stop"] and state["stop_reason"]:
            session.stop_reason = state["stop_reason"]
        await rt.db.commit()
    return state


def should_continue(state: AgentState) -> str:
    if state.get("should_stop"):
        return "generate_report"
    return "plan_action"


async def generate_report(state: AgentState) -> AgentState:
    findings = [FindingCandidate.model_validate(f) for f in state["findings"]]
    lines = [
        "# BugPilot scan report",
        "",
        f"URL: {state['start_url']}",
        f"Scope: {state.get('scope_type', 'full_site')}",
        f"Pages: {state['pages_visited']}",
        f"Actions: {state['actions_taken']}",
        "",
    ]
    if state.get("stop_reason"):
        lines += [f"Stopped because: {state['stop_reason']}", ""]
    for finding in findings:
        lines += [f"## {finding.title}", finding.description, ""]
    state["report_markdown"] = "\n".join(lines)
    await emit(
        "scan.completed",
        "Scan complete",
        MascotState.SUCCESS,
        {
            "stop_reason": state.get("stop_reason"),
            "findings": len(findings),
            "pages": state["pages_visited"],
        },
    )
    return state


def build_graph():
    graph = StateGraph(AgentState)
    graph.add_node("initialize", initialize)
    graph.add_node("analyze_page", analyze_page)
    graph.add_node("discover_elements", discover_elements)
    graph.add_node("plan_action", plan_action)
    graph.add_node("execute_action", execute_action)
    graph.add_node("observe", observe)
    graph.add_node("run_detectors", run_detector_node)
    graph.add_node("analyze_suspicious", analyze_suspicious)
    graph.add_node("collect_evidence", collect_evidence)
    graph.add_node("verify_findings", verify_findings)
    graph.add_node("update_state", update_state)
    graph.add_node("generate_report", generate_report)

    graph.add_edge(START, "initialize")
    graph.add_edge("initialize", "analyze_page")
    graph.add_edge("analyze_page", "discover_elements")
    graph.add_edge("discover_elements", "run_detectors")
    graph.add_edge("plan_action", "execute_action")
    graph.add_edge("execute_action", "observe")
    graph.add_edge("observe", "run_detectors")
    graph.add_edge("run_detectors", "analyze_suspicious")
    graph.add_edge("analyze_suspicious", "collect_evidence")
    graph.add_edge("collect_evidence", "verify_findings")
    graph.add_edge("verify_findings", "update_state")
    graph.add_conditional_edges(
        "update_state",
        should_continue,
        {"plan_action": "plan_action", "generate_report": "generate_report"},
    )
    graph.add_edge("generate_report", END)
    return graph.compile()
