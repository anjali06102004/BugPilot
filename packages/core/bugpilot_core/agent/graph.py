from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse
from uuid import uuid4

from langgraph.graph import END, START, StateGraph
from sqlalchemy.ext.asyncio import AsyncSession

from bugpilot_core.agent.browser import BrowserSession
from bugpilot_core.agent.state import AgentState
from bugpilot_core.ai import build_provider
from bugpilot_core.ai.prompts import REASONING_PROMPT_V1, VISION_PROMPT_V1
from bugpilot_core.ai.providers.base import AIProvider, VisionAnalysis
from bugpilot_core.config import Settings
from bugpilot_core.db.models import (
    ActionRecord,
    Finding,
    FindingEvidence,
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
    FindingStatus,
    MascotState,
    PlannedAction,
    ScanConfig,
    ScanEvent,
    TestCategory,
    Viewport,
)
from bugpilot_core.policies.action_policy import ActionPolicy
from bugpilot_core.scoring.actions import score_action
from bugpilot_core.severity import score_severity

RUNTIME: ContextVar["AgentRuntime"] = ContextVar("bugpilot_runtime")


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


async def initialize(state: AgentState) -> AgentState:
    rt = runtime()
    await emit("scan.started", "🐞 Starting scan", MascotState.FLYING)
    await rt.session.goto(state["start_url"])
    state["current_url"] = rt.session.page.url if rt.session.page else state["start_url"]
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
        MascotState.INSPECTING,
        {
            "url": snap.url,
            "screenshot": f"/evidence/{state['session_id']}/{Path(snap.screenshot_path).name}" if snap.screenshot_path else None,
            "title": snap.title,
        },
    )
    page = PageRecord(
        id=str(uuid4()),
        session_id=state["session_id"],
        url=snap.url,
        title=snap.title,
        viewport_name=viewport.name,
        screenshot_path=snap.screenshot_path,
    )
    rt.db.add(page)
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
    state["last_observation_summary"] = f"{snap.title}: {len(interactive)} interactive elements"
    if snap.url not in state["visited_urls"]:
        state["visited_urls"] = [*state["visited_urls"], snap.url]
    state["pages_visited"] = len(state["visited_urls"])
    return state


def _plan_from_snapshot(state: AgentState) -> list[PlannedAction]:
    rt = runtime()
    snap = rt.snapshot_cache["current"]
    seen = set(state["tested_fingerprints"])
    visited = set(state["visited_urls"])
    actions: list[PlannedAction] = []
    origin = urlparse(state["start_url"]).netloc

    for el in snap.elements:
        if not el.visible:
            continue
        if el.interactive and (el.tag in {"a", "button"} or el.role in {"link", "button"}):
            href = el.href or ""
            abs_url = urljoin(snap.url, href) if href else None
            action_type = ActionType.NAVIGATE if abs_url and href else ActionType.CLICK
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
        if el.tag in {"input", "textarea"} and el.attributes.get("type") not in {"hidden", "submit"}:
            planned = PlannedAction(
                type=ActionType.FILL,
                selector=el.selector,
                fingerprint=el.fingerprint,
                value="test@example.com" if "email" in (el.type or el.name or "") else "BugPilot sample",
                description=f"fill {el.selector}",
            )
            planned = rt.policy.evaluate(planned, el.text, "")
            actions.append(score_action(planned, el, seen_fingerprints=seen, visited_urls=visited))

    planned = PlannedAction(type=ActionType.SCROLL, description="Scroll the page", selector="body")
    actions.append(score_action(planned, None, seen_fingerprints=seen, visited_urls=visited))
    if TestCategory.RESPONSIVE in rt.config.categories:
        for vp in rt.config.viewports[1:]:
            planned = PlannedAction(
                type=ActionType.RESIZE,
                description=f"Resize to {vp.name} {vp.width}x{vp.height}",
                value=json_dumps(vp.model_dump()),
                fingerprint=f"resize:{vp.name}",
            )
            actions.append(score_action(planned, None, seen_fingerprints=seen, visited_urls=visited))
    actions = [a for a in actions if not a.blocked_by_policy]
    actions.sort(key=lambda a: a.score, reverse=True)
    return actions[:12]


def json_dumps(value: Any) -> str:
    import json

    return json.dumps(value)


async def discover_elements(state: AgentState) -> AgentState:
    actions = _plan_from_snapshot(state)
    await emit("action.started", f"Planning {len(actions)} candidate actions", MascotState.EXPLORING)
    state["pending_actions"] = [a.model_dump() for a in actions]
    return state


async def plan_action(state: AgentState) -> AgentState:
    if not state["pending_actions"]:
        state["pending_actions"] = [a.model_dump() for a in _plan_from_snapshot(state)]
    return state


async def execute_action(state: AgentState) -> AgentState:
    rt = runtime()
    pending = list(state["pending_actions"])
    if not pending:
        return state
    action = PlannedAction.model_validate(pending.pop(0))
    state["pending_actions"] = pending
    if action.fingerprint:
        state["tested_fingerprints"] = [*state["tested_fingerprints"], action.fingerprint]
    await emit(
        "action.started",
        f"🐞 {action.description}",
        MascotState.EXPLORING,
        {"action": action.model_dump()},
    )
    try:
        if action.type == ActionType.CLICK and action.selector:
            await rt.session.click(action.selector)
        elif action.type == ActionType.NAVIGATE and action.selector:
            previous = state["current_url"]
            await rt.session.click(action.selector)
            new_url = rt.session.page.url if rt.session.page else previous
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
            import json

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
        await emit("action.completed", f"Completed: {action.description}", MascotState.EXPLORING)
    except Exception as exc:
        await emit("action.completed", f"Action failed (recovered): {action.description}", MascotState.ERROR, {"error": str(exc)})
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
        await emit("detector.triggered", f"⚠ {len(merged)} suspicious signal(s)", MascotState.SUSPICIOUS)
        state["suspicious"] = True
    else:
        state["suspicious"] = False
    existing = [FindingCandidate.model_validate(f) for f in state["findings"]]
    combined = dedupe_candidates(existing + merged)
    state["findings"] = [c.model_dump() for c in combined]
    return state


async def analyze_suspicious(state: AgentState) -> AgentState:
    if not state["suspicious"]:
        return state
    rt = runtime()
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
            {"tag": el.tag, "text": el.text, "selector": el.selector, "box": el.box.model_dump() if el.box else None}
            for el in snap.elements
            if el.interactive
        ][:40],
        "previous_observation": state["last_observation_summary"],
        "detector_findings": state["findings"][-5:],
    }
    started = datetime.now(timezone.utc)
    analysis: VisionAnalysis = await rt.ai.analyze_vision(
        prompt=VISION_PROMPT_V1, image_bytes=image_bytes, context=context
    )
    latency = int((datetime.now(timezone.utc) - started).total_seconds() * 1000)
    rt.db.add(
        ModelRun(
            id=str(uuid4()),
            session_id=state["session_id"],
            prompt_name="vision_detector",
            prompt_version="v1",
            provider=rt.ai.capabilities().name,
            model=rt.settings.gemini_model if rt.settings.ai_provider == "gemini" else rt.settings.openai_model,
            latency_ms=latency,
        )
    )
    await rt.db.commit()
    extra: list[FindingCandidate] = []
    for anomaly in analysis.anomalies:
        extra.append(
            FindingCandidate(
                category=__import__("bugpilot_core.models", fromlist=["FindingCategory"]).FindingCategory.VISUAL,
                title=anomaly.title,
                description=anomaly.description,
                confidence=anomaly.confidence,
                source="ai_reasoning",
                selector=anomaly.selector_hint,
                url=snap.url,
                viewport=snap.viewport,
                expected=anomaly.expected,
                actual=anomaly.actual,
            )
        )
    if extra:
        combined = dedupe_candidates([FindingCandidate.model_validate(f) for f in state["findings"]] + extra)
        state["findings"] = [c.model_dump() for c in combined]
    await emit("detector.triggered", "🔍 Running visual analysis", MascotState.INSPECTING)
    return state


async def collect_evidence(state: AgentState) -> AgentState:
    return state


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
        started = datetime.now(timezone.utc)
        reasoning = await rt.ai.reason(
            prompt=REASONING_PROMPT_V1,
            context={"candidate": candidate.model_dump(mode="json"), "url": snap.url},
        )
        rt.db.add(
            ModelRun(
                id=str(uuid4()),
                session_id=state["session_id"],
                prompt_name="reasoning_agent",
                prompt_version="v1",
                provider=rt.ai.capabilities().name,
                model=rt.settings.gemini_model,
                latency_ms=int((datetime.now(timezone.utc) - started).total_seconds() * 1000),
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
            await emit("verification.completed", f"🐞 Bug confirmed: {candidate.title}", MascotState.BUG_FOUND)
    state["findings"] = [c.model_dump() for c in verified]
    await persist_findings(state)
    return state


async def persist_findings(state: AgentState) -> None:
    rt = runtime()
    from sqlalchemy import select

    rows = (await rt.db.execute(select(Finding).where(Finding.session_id == state["session_id"]))).scalars().all()
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
                confidence=candidate.confidence,
                confidence_label=conf_label.value,
                status=status.value,
                source=candidate.source,
                url=candidate.url,
                selector=candidate.selector,
                fingerprint=candidate.fingerprint,
                expected=candidate.expected,
                actual=candidate.actual,
                steps_json=candidate.steps,
                suggested_fix=candidate.metadata.get("suggested_fix"),
                root_cause=candidate.metadata.get("root_cause"),
                reproduced_count=1 if reproduced else 0,
                verification_attempts=1,
                extra=candidate.metadata,
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
            await emit(
                "finding.created",
                f"Finding: {candidate.title}",
                MascotState.BUG_FOUND if status == FindingStatus.VERIFIED else MascotState.SUSPICIOUS,
                {"finding_id": finding.id, "title": candidate.title, "severity": severity.value, "status": status.value},
            )
        else:
            finding.verification_attempts += 1
            if reproduced:
                finding.reproduced_count += 1
                finding.status = FindingStatus.VERIFIED.value
                finding.confidence_label = ConfidenceLabel.CONFIRMED.value
    await rt.db.commit()


async def update_state(state: AgentState) -> AgentState:
    rt = runtime()
    elapsed = (datetime.now(timezone.utc) - rt.started_at).total_seconds()
    if elapsed >= rt.config.max_duration_seconds:
        state["should_stop"] = True
        state["stop_reason"] = "Scan duration budget reached"
    elif state["pages_visited"] >= rt.config.max_pages:
        state["should_stop"] = True
        state["stop_reason"] = "Page budget reached"
    elif state["actions_taken"] >= rt.config.max_actions:
        state["should_stop"] = True
        state["stop_reason"] = "Action budget reached"
    elif not state["pending_actions"]:
        refreshed = _plan_from_snapshot(state)
        unused = [a for a in refreshed if a.fingerprint not in set(state["tested_fingerprints"])]
        if unused:
            state["pending_actions"] = [a.model_dump() for a in unused[:8]]
        else:
            state["should_stop"] = True
            state["stop_reason"] = "No new states to explore"
    session = await rt.db.get(TestSession, state["session_id"])
    if session:
        session.pages_tested = state["pages_visited"]
        session.actions_taken = state["actions_taken"]
        await rt.db.commit()
    return state


def should_continue(state: AgentState) -> str:
    if state.get("should_stop"):
        return "generate_report"
    return "plan_action"


async def generate_report(state: AgentState) -> AgentState:
    findings = [FindingCandidate.model_validate(f) for f in state["findings"]]
    lines = ["# BugPilot scan report", "", f"URL: {state['start_url']}", f"Pages: {state['pages_visited']}", ""]
    for finding in findings:
        lines += [f"## {finding.title}", finding.description, ""]
    state["report_markdown"] = "\n".join(lines)
    await emit("scan.completed", "Scan complete", MascotState.SUCCESS, {"stop_reason": state.get("stop_reason")})
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
    graph.add_conditional_edges("update_state", should_continue, {"plan_action": "plan_action", "generate_report": "generate_report"})
    graph.add_edge("generate_report", END)
    return graph.compile()
