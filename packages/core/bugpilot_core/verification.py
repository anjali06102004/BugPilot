"""Post-fix verification.

A scan tells you a defect existed. Verification answers a different question:
*does it still reproduce now?* That requires replaying the reproduction the
agent recorded, re-running the same deterministic checks, and being explicit
when the answer is "I could not tell".

Rules:
- a screenshot or an HTTP 200 never proves a fix
- a failed navigation, a missing selector or a replay that could not run is
  `inconclusive`, never `fixed`
- only a successful replay where the detector no longer matches is `fixed`
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from bugpilot_core.agent.browser import BrowserSession
from bugpilot_core.config import Settings
from bugpilot_core.detectors import run_detectors
from bugpilot_core.detectors.base import PageSnapshot
from bugpilot_core.models import (
    ActionType,
    FindingCandidate,
    ScanConfig,
    ScanEvent,
    TestCategory,
    Viewport,
)
from bugpilot_core.policies.action_policy import ActionPolicy

Verdict = Literal["fixed", "still_failing", "inconclusive"]

# Verification is bounded: a stuck replay must report inconclusive quickly
# instead of holding a worker for minutes.
REPLAY_BUDGET_SECONDS = 30.0
REPLAY_ACTION_TIMEOUT_MS = 2500

CATEGORY_TO_TEST: dict[str, TestCategory] = {
    "visual": TestCategory.VISUAL,
    "layout": TestCategory.VISUAL,
    "overflow": TestCategory.RESPONSIVE,
    "broken_image": TestCategory.CONTENT,
    "console": TestCategory.CONSOLE,
    "network": TestCategory.NETWORK,
    "accessibility": TestCategory.ACCESSIBILITY,
    "responsive": TestCategory.RESPONSIVE,
    "navigation": TestCategory.NAVIGATION,
    "forms": TestCategory.FORMS,
    "content": TestCategory.CONTENT,
    "functional": TestCategory.FUNCTIONAL,
}


@dataclass
class VerificationOutcome:
    verdict: Verdict
    method: str
    notes: str
    evidence_path: str | None = None
    actions_replayed: int = 0
    actions_failed: int = 0
    candidates_after: list[FindingCandidate] = field(default_factory=list)


def normalise(value: str | None) -> str:
    import re

    if not value:
        return ""
    text = re.sub(r"\d+", "#", value.lower())
    return " ".join(re.sub(r"[^a-z0-9#]+", " ", text).split())[:200]


def matches_issue(
    issue_snapshot: dict[str, Any],
    candidates: list[FindingCandidate],
) -> FindingCandidate | None:
    """Find the candidate that represents the same defect as the issue."""
    signature = normalise(issue_snapshot.get("error_signature"))
    fingerprint = issue_snapshot.get("fingerprint")
    selector = issue_snapshot.get("selector")
    title = (issue_snapshot.get("title") or "").lower().strip()
    for candidate in candidates:
        if signature and normalise(candidate.error_signature) == signature:
            return candidate
        if fingerprint and candidate.fingerprint == fingerprint:
            return candidate
        if selector and candidate.selector == selector:
            return candidate
        if title and candidate.title.lower().strip() == title:
            return candidate
    return None


def evaluate_verification(
    *,
    candidates_after: list[FindingCandidate],
    issue_snapshot: dict[str, Any],
    page_loaded: bool,
    replay_failures: int,
    element_required: bool,
    element_found: bool,
    replay_incomplete: bool = False,
) -> tuple[Verdict, str]:
    """Decide the verdict, and say exactly why."""
    if replay_incomplete:
        return (
            "inconclusive",
            "The replay did not finish within the time budget, so the original state was not reached.",
        )
    if not page_loaded:
        return "inconclusive", "The reproduction URL could not be loaded."
    if element_required and not element_found:
        return (
            "inconclusive",
            "The element from the original reproduction no longer exists, so the defect "
            "cannot be re-checked automatically.",
        )
    if replay_failures > 0:
        return (
            "inconclusive",
            f"{replay_failures} replay step(s) failed, so the original state was not reached.",
        )
    if matches_issue(issue_snapshot, candidates_after):
        return "still_failing", "The same detector signal is still present after replaying the steps."
    return "fixed", "The recorded reproduction completed and the detector signal is gone."


async def _noop_emit(_event: ScanEvent) -> None:
    return None


async def verify_issue(
    issue: Any,
    *,
    settings: Settings,
    author: str | None = None,
) -> VerificationOutcome:
    """Replay the stored reproduction and re-run the relevant detectors."""
    extra = issue.extra if isinstance(issue.extra, dict) else {}
    reproduction = extra.get("reproduction") or {}
    url = reproduction.get("url") or issue.url
    actions = [a for a in (reproduction.get("actions") or []) if isinstance(a, dict)]
    if not url:
        return VerificationOutcome(
            verdict="inconclusive",
            method="replay",
            notes="No reproduction URL was recorded for this issue.",
        )

    viewport_data = reproduction.get("viewport") or {}
    viewport = Viewport(
        name=viewport_data.get("name") or issue.viewport or "desktop-1280",
        width=int(viewport_data.get("width") or 1280),
        height=int(viewport_data.get("height") or 720),
    )
    config = ScanConfig(
        viewports=[viewport],
        max_pages=1,
        max_actions=len(actions) + 2,
        max_duration_seconds=60,
        environment=issue.environment or "staging",  # type: ignore[arg-type]
    )
    policy = ActionPolicy(allow_destructive=False, environment=config.environment)
    session_id = f"verify-{uuid4().hex[:12]}"
    browser = BrowserSession(
        session_id=session_id,
        config=config,
        evidence_dir=settings.evidence_dir,
        emit=_noop_emit,
    )

    page_loaded = False
    load_error: str | None = None
    replay_incomplete = False
    replay_deadline = time.monotonic() + REPLAY_BUDGET_SECONDS
    replayed = 0
    failures = 0
    element_required = bool(reproduction.get("selector") or issue.selector)
    selector = reproduction.get("selector") or issue.selector
    element_found = False
    snapshot: PageSnapshot | None = None
    evidence_path: str | None = None

    try:
        await browser.start()
        try:
            await browser.goto(url)
            page_loaded = True
        except Exception as exc:
            page_loaded = False
            load_error = str(exc)
        if page_loaded:
            for action in actions[:15]:
                if time.monotonic() >= replay_deadline:
                    replay_incomplete = True
                    break
                kind = str(action.get("type") or "")
                action_selector = action.get("selector")
                if kind not in {"click", "fill", "hover", "scroll"} or not action_selector:
                    continue
                planned = policy.evaluate(
                    _planned(kind, action_selector, action.get("value")),
                    element_text="",
                    href=str(action.get("url") or ""),
                )
                if planned.blocked_by_policy:
                    failures += 1
                    continue
                try:
                    if kind == "click":
                        await browser.click(action_selector, timeout_ms=REPLAY_ACTION_TIMEOUT_MS)
                    elif kind == "fill":
                        await browser.fill(
                            action_selector,
                            str(action.get("value") or "sample"),
                            timeout_ms=REPLAY_ACTION_TIMEOUT_MS,
                        )
                    elif kind == "hover":
                        await browser.hover(action_selector, timeout_ms=REPLAY_ACTION_TIMEOUT_MS)
                    else:
                        await browser.scroll()
                    replayed += 1
                except Exception:
                    failures += 1
            snapshot = await browser.snapshot(viewport)
            evidence_path = snapshot.screenshot_path
            if selector:
                try:
                    element_found = await browser.page.locator(selector).count() > 0
                except Exception:
                    element_found = False
    finally:
        await browser.close()

    if snapshot is None:
        return VerificationOutcome(
            verdict="inconclusive",
            method="replay",
            notes=(
                "The reproduction URL could not be loaded, so the fix cannot be confirmed"
                + (f": {load_error}" if load_error else ".")
            ),
            evidence_path=evidence_path,
            actions_replayed=replayed,
            actions_failed=failures,
        )

    category = CATEGORY_TO_TEST.get(issue.category, TestCategory.VISUAL)
    candidates = run_detectors(snapshot, [category, TestCategory.CONSOLE, TestCategory.NETWORK])
    verdict, notes = evaluate_verification(
        candidates_after=candidates,
        issue_snapshot={
            "error_signature": reproduction.get("error_signature") or getattr(issue, "error_signature", None),
            "fingerprint": issue.fingerprint,
            "selector": selector,
            "title": issue.title,
        },
        page_loaded=page_loaded,
        replay_failures=failures,
        replay_incomplete=replay_incomplete,
        element_required=element_required,
        element_found=element_found,
    )
    return VerificationOutcome(
        verdict=verdict,
        method="replay",
        notes=notes,
        evidence_path=evidence_path,
        actions_replayed=replayed,
        actions_failed=failures,
        candidates_after=candidates,
    )


def _planned(kind: str, selector: str, value: Any):
    from bugpilot_core.models import PlannedAction

    return PlannedAction(
        type=ActionType(kind),
        selector=selector,
        value=str(value) if value is not None else None,
        description=f"replay {kind} {selector}",
    )


def verification_id() -> str:
    return hashlib.sha1(f"{datetime.now(UTC).timestamp()}{uuid4()}".encode()).hexdigest()[:32]


def store_screenshot(settings: Settings, path: str | None, session_id: str) -> str | None:
    """Copy a verification screenshot into the evidence directory layout."""
    if not path:
        return None
    source = Path(path)
    if not source.exists():
        return None
    return str(source)
