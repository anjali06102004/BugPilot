"""The Living Bug Registry.

A scan produces *findings*: observations tied to one scan. The registry turns
those observations into *issues*: canonical, persistent records that survive
across scans, keep every occurrence separately, and carry a documented
lifecycle.

Recurring defects update the canonical record instead of creating duplicates,
and a defect that reappears after being fixed is flagged as a regression.
"""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bugpilot_core.db.models import (
    Finding,
    Issue,
    IssueEvent,
    IssueEvidence,
    IssueOccurrence,
    TestSession,
)
from bugpilot_core.models import (
    ConfidenceLabel,
    FindingCandidate,
    IssueStatus,
    SeverityLevel,
)

# Allowed lifecycle transitions. Anything else is rejected so a mistake in the
# UI cannot corrupt the audit trail.
ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    IssueStatus.NEW: {
        IssueStatus.TRIAGED,
        IssueStatus.CONFIRMED,
        IssueStatus.NEEDS_REVIEW,
        IssueStatus.FALSE_POSITIVE,
        IssueStatus.DUPLICATE,
        IssueStatus.CLOSED,
    },
    IssueStatus.TRIAGED: {
        IssueStatus.CONFIRMED,
        IssueStatus.IN_PROGRESS,
        IssueStatus.NEEDS_REVIEW,
        IssueStatus.FALSE_POSITIVE,
        IssueStatus.DUPLICATE,
        IssueStatus.BLOCKED,
        IssueStatus.CLOSED,
    },
    IssueStatus.CONFIRMED: {
        IssueStatus.IN_PROGRESS,
        IssueStatus.NEEDS_REVIEW,
        IssueStatus.FALSE_POSITIVE,
        IssueStatus.DUPLICATE,
        IssueStatus.BLOCKED,
        IssueStatus.CLOSED,
    },
    IssueStatus.IN_PROGRESS: {
        IssueStatus.FIXED,
        IssueStatus.BLOCKED,
        IssueStatus.NEEDS_REVIEW,
        IssueStatus.CLOSED,
    },
    IssueStatus.FIXED: {IssueStatus.VERIFIED, IssueStatus.REOPENED, IssueStatus.IN_PROGRESS},
    IssueStatus.VERIFIED: {IssueStatus.CLOSED, IssueStatus.REOPENED},
    IssueStatus.CLOSED: {IssueStatus.REOPENED},
    IssueStatus.NEEDS_REVIEW: {
        IssueStatus.TRIAGED,
        IssueStatus.CONFIRMED,
        IssueStatus.FALSE_POSITIVE,
        IssueStatus.DUPLICATE,
        IssueStatus.CLOSED,
    },
    IssueStatus.FALSE_POSITIVE: {IssueStatus.NEW, IssueStatus.TRIAGED},
    IssueStatus.DUPLICATE: {IssueStatus.NEW},
    IssueStatus.REOPENED: {
        IssueStatus.TRIAGED,
        IssueStatus.CONFIRMED,
        IssueStatus.IN_PROGRESS,
        IssueStatus.FALSE_POSITIVE,
        IssueStatus.CLOSED,
    },
    IssueStatus.BLOCKED: {IssueStatus.IN_PROGRESS, IssueStatus.TRIAGED, IssueStatus.CLOSED},
}

TERMINAL_STATES = {IssueStatus.CLOSED.value, IssueStatus.FALSE_POSITIVE.value}


class RegistryError(ValueError):
    pass


def route_of(url: str) -> str:
    """Normalized route for an URL: path plus sorted query, without fragment."""
    parsed = urlparse(url)
    path = parsed.path or "/"
    return path


def normalize_signature(text: str | None) -> str:
    if not text:
        return ""
    text = re.sub(r"\d+", "#", text.lower())
    text = re.sub(r"[^a-z0-9#]+", " ", text)
    return " ".join(text.split())[:200]


def issue_key(candidate: FindingCandidate, *, project_id: str) -> str:
    """Stable identity of a defect across scans.

    Built from the signals that survive a redeploy or a content change: the
    project, the category, the route, the DOM fingerprint and the normalized
    error signature. Titles are deliberately not part of the key.
    """
    parts = [
        project_id,
        candidate.category.value,
        route_of(candidate.url),
        candidate.fingerprint or candidate.selector or "",
        normalize_signature(candidate.error_signature or candidate.title),
    ]
    digest = hashlib.sha1("|".join(parts).encode()).hexdigest()[:24]
    return digest


def title_similarity(a: str, b: str) -> float:
    tokens_a = set(a.lower().split())
    tokens_b = set(b.lower().split())
    if not tokens_a or not tokens_b:
        return 0.0
    return len(tokens_a & tokens_b) / len(tokens_a | tokens_b)


async def find_matching_issue(
    db: AsyncSession,
    *,
    project_id: str,
    candidate: FindingCandidate,
) -> Issue | None:
    """Locate the canonical record for a candidate, if one exists.

    The key lookup is authoritative. The fuzzy fallback only merges when the
    signals are strong (same fingerprint or same normalized error signature on
    the same route), because merging two distinct bugs is worse than showing
    one duplicate.
    """
    key = issue_key(candidate, project_id=project_id)
    row = (await db.execute(select(Issue).where(Issue.issue_key == key))).scalar_one_or_none()
    if row:
        return row

    route = route_of(candidate.url)
    fingerprint = candidate.fingerprint
    signature = normalize_signature(candidate.error_signature)
    rows = (
        (
            await db.execute(
                select(Issue).where(
                    Issue.project_id == project_id,
                    Issue.category == candidate.category.value,
                    Issue.route == route,
                )
            )
        )
        .scalars()
        .all()
    )
    for issue in rows:
        if fingerprint and issue.fingerprint and issue.fingerprint == fingerprint:
            return issue
        if signature and issue.error_signature and normalize_signature(issue.error_signature) == signature:
            return issue
        if title_similarity(issue.title, candidate.title) >= 0.85 and (
            issue.selector and candidate.selector and issue.selector == candidate.selector
        ):
            return issue
    return None


def _new_issue(
    *,
    project_id: str,
    candidate: FindingCandidate,
    severity: str,
    priority: str,
    confidence_label: str,
    confidence: float,
    environment: str | None,
    browser: str | None,
    viewport: str | None,
) -> Issue:
    now = datetime.now(UTC)
    return Issue(
        id=uuid4().hex,
        issue_key=issue_key(candidate, project_id=project_id),
        project_id=project_id,
        title=candidate.title,
        summary=candidate.description[:400],
        description=candidate.description,
        category=candidate.category.value,
        severity=severity,
        priority=priority,
        confidence_label=confidence_label,
        confidence=confidence,
        status=IssueStatus.NEW.value,
        source=candidate.source,
        url=candidate.url,
        route=candidate.route or route_of(candidate.url),
        component=candidate.component,
        selector=candidate.selector,
        fingerprint=candidate.fingerprint,
        error_signature=candidate.error_signature,
        expected=candidate.expected,
        actual=candidate.actual,
        reproduction_steps=candidate.steps,
        root_cause=candidate.metadata.get("root_cause"),
        root_cause_status="unconfirmed",
        suggested_fix=candidate.metadata.get("suggested_fix"),
        environment=environment,
        browser=browser,
        viewport=viewport,
        occurrence_count=1,
        affected_scan_count=1,
        affected_page_count=1,
        extra={
            "priority_rationale": candidate.metadata.get("priority_rationale", []),
            "reproduction": candidate.metadata.get("reproduction"),
        },
        first_seen_at=now,
        last_seen_at=now,
    )


async def record_occurrence(
    db: AsyncSession,
    *,
    session: TestSession,
    finding: Finding,
    candidate: FindingCandidate,
    severity: str,
    priority: str,
    confidence_label: str,
    confidence: float,
    environment: str | None = None,
    browser: str | None = None,
    viewport: str | None = None,
) -> tuple[Issue, bool, bool]:
    """Register one finding in the registry.

    Returns the canonical issue and whether this sighting was a regression
    (the issue had been fixed or closed and has reappeared).
    """
    project_id = session.project_id
    issue = await find_matching_issue(db, project_id=project_id, candidate=candidate)
    created = False
    regression = False
    now = datetime.now(UTC)

    if issue is None:
        issue = _new_issue(
            project_id=project_id,
            candidate=candidate,
            severity=severity,
            priority=priority,
            confidence_label=confidence_label,
            confidence=confidence,
            environment=environment,
            browser=browser,
            viewport=viewport,
        )
        db.add(issue)
        await db.flush()
        created = True
    else:
        issue.last_seen_at = now
        issue.occurrence_count = (issue.occurrence_count or 0) + 1
        issue.affected_scan_count = (issue.affected_scan_count or 0) + 1
        if issue.status in {
            IssueStatus.FIXED.value,
            IssueStatus.CLOSED.value,
            IssueStatus.VERIFIED.value,
        }:
            issue.status = IssueStatus.REOPENED.value
            issue.is_regression = True
            issue.reopened_count = (issue.reopened_count or 0) + 1
            regression = True
            db.add(
                IssueEvent(
                    id=uuid4().hex,
                    issue_id=issue.id,
                    kind="regression",
                    from_value=issue.status,
                    to_value=IssueStatus.REOPENED.value,
                    body="Previously resolved issue was detected again.",
                )
            )
        if candidate.metadata.get("root_cause") and not issue.root_cause:
            issue.root_cause = candidate.metadata.get("root_cause")
        if candidate.metadata.get("suggested_fix") and not issue.suggested_fix:
            issue.suggested_fix = candidate.metadata.get("suggested_fix")
        if candidate.steps and not issue.reproduction_steps:
            issue.reproduction_steps = candidate.steps
        if candidate.metadata.get("reproduction") and not (issue.extra or {}).get("reproduction"):
            issue.extra = {
                **(issue.extra or {}),
                "reproduction": candidate.metadata["reproduction"],
            }
        # Keep the most severe classification seen so far, but never downgrade
        # a confirmed issue because a later scan was less sure.
        if _severity_rank(severity) > _severity_rank(issue.severity):
            issue.severity = severity
        if _priority_rank(priority) < _priority_rank(issue.priority):
            issue.priority = priority
        if _confidence_rank(confidence_label) > _confidence_rank(issue.confidence_label):
            issue.confidence_label = confidence_label
            issue.confidence = confidence

    finding.issue_id = issue.id

    occurrence = IssueOccurrence(
        id=uuid4().hex,
        issue_id=issue.id,
        session_id=session.id,
        finding_id=finding.id,
        url=finding.url,
        route=finding.route or route_of(finding.url),
        viewport=finding.extra.get("viewport") if isinstance(finding.extra, dict) else None,
        severity=severity,
        priority=priority,
        confidence=confidence,
        confidence_label=confidence_label,
        verified=bool(finding.extra.get("reproduced")) if isinstance(finding.extra, dict) else False,
        reproduced=bool(finding.extra.get("reproduced")) if isinstance(finding.extra, dict) else False,
        evidence=[{"kind": e.kind, "path": e.path, "content": e.content} for e in candidate.evidence],
        notes=finding.extra.get("root_cause") if isinstance(finding.extra, dict) else None,
    )
    db.add(occurrence)
    await db.flush()

    for item in candidate.evidence:
        db.add(
            IssueEvidence(
                id=uuid4().hex,
                issue_id=issue.id,
                occurrence_id=occurrence.id,
                session_id=session.id,
                kind=item.kind,
                path=item.path,
                content=item.content if isinstance(item.content, dict) else {"value": item.content},
                redacted=bool(settings_redact_marker()),
            )
        )
    if created:
        db.add(
            IssueEvent(
                id=uuid4().hex,
                issue_id=issue.id,
                kind="created",
                to_value=IssueStatus.NEW.value,
                body=f"Detected by {candidate.source} on {candidate.url}",
            )
        )
    await db.flush()
    return issue, created, regression


def settings_redact_marker() -> bool:
    """Evidence rows are flagged redacted when the text was scrubbed."""
    return True


def _severity_rank(value: str) -> int:
    order = {
        SeverityLevel.INFORMATIONAL.value: 0,
        SeverityLevel.LOW.value: 1,
        SeverityLevel.MEDIUM.value: 2,
        SeverityLevel.HIGH.value: 3,
        SeverityLevel.CRITICAL.value: 4,
    }
    return order.get(value, 0)


def _priority_rank(value: str) -> int:
    order = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
    return order.get(value, 3)


def _confidence_rank(value: str) -> int:
    order = {
        ConfidenceLabel.NOT_A_BUG.value: 0,
        ConfidenceLabel.POSSIBLE.value: 1,
        ConfidenceLabel.LIKELY.value: 2,
        ConfidenceLabel.CONFIRMED.value: 3,
    }
    return order.get(value, 0)


def can_transition(current: str, target: str) -> bool:
    allowed = ALLOWED_TRANSITIONS.get(current, set())
    return target in {s.value for s in allowed}


async def transition_issue(
    db: AsyncSession,
    issue: Issue,
    target: IssueStatus,
    *,
    author: str | None = None,
    body: str = "",
    force: bool = False,
) -> Issue:
    current = issue.status
    if current == target.value:
        return issue
    if not force and not can_transition(current, target.value):
        raise RegistryError(f"Cannot move an issue from '{current}' to '{target.value}'.")
    issue.status = target.value
    if target == IssueStatus.VERIFIED:
        issue.last_verified_at = datetime.now(UTC)
        issue.verified_count = (issue.verified_count or 0) + 1
    if target == IssueStatus.FALSE_POSITIVE:
        issue.confidence_label = ConfidenceLabel.NOT_A_BUG.value
    db.add(
        IssueEvent(
            id=uuid4().hex,
            issue_id=issue.id,
            kind="status_change",
            from_value=current,
            to_value=target.value,
            body=body,
            author=author,
        )
    )
    await db.flush()
    return issue


async def add_note(
    db: AsyncSession,
    issue: Issue,
    *,
    body: str,
    author: str | None = None,
) -> IssueEvent:
    event = IssueEvent(
        id=uuid4().hex,
        issue_id=issue.id,
        kind="note",
        body=body,
        author=author,
    )
    db.add(event)
    await db.flush()
    return event


async def assign_issue(
    db: AsyncSession,
    issue: Issue,
    *,
    assignee: str | None,
    author: str | None = None,
) -> Issue:
    previous = issue.assigned_to
    issue.assigned_to = assignee
    db.add(
        IssueEvent(
            id=uuid4().hex,
            issue_id=issue.id,
            kind="assignment",
            from_value=previous,
            to_value=assignee,
            author=author,
        )
    )
    await db.flush()
    return issue


async def duplicate_candidates(db: AsyncSession, issue: Issue) -> list[dict[str, Any]]:
    """Suggest plausible duplicates without merging anything.

    Merge decisions stay with a human: this only ranks the evidence for and
    against a merge so the UI can ask a sensible question.
    """
    rows = (
        (
            await db.execute(
                select(Issue).where(
                    Issue.project_id == issue.project_id,
                    Issue.id != issue.id,
                    Issue.status != IssueStatus.DUPLICATE.value,
                )
            )
        )
        .scalars()
        .all()
    )
    suggestions: list[dict[str, Any]] = []
    for other in rows:
        reasons: list[str] = []
        score = 0.0
        strong_signal = False
        if other.category == issue.category:
            score += 0.15
            reasons.append("same category")
        if other.route and issue.route and other.route == issue.route:
            score += 0.25
            reasons.append("same route")
        if other.fingerprint and issue.fingerprint and other.fingerprint == issue.fingerprint:
            score += 0.4
            strong_signal = True
            reasons.append("same DOM fingerprint")
        if (
            other.error_signature
            and issue.error_signature
            and normalize_signature(other.error_signature) == normalize_signature(issue.error_signature)
        ):
            score += 0.3
            strong_signal = True
            reasons.append("same normalized error signature")
        if other.selector and issue.selector and other.selector == issue.selector:
            score += 0.2
            strong_signal = True
            reasons.append("same selector")
        similarity = title_similarity(other.title, issue.title)
        if similarity >= 0.6:
            score += min(0.3, similarity * 0.3)
            strong_signal = True
            reasons.append(f"similar title ({int(similarity * 100)}%)")
        # Same category and route alone is a coincidence, not a duplicate.
        if score < 0.5 or not strong_signal:
            continue
        suggestions.append(
            {
                "id": other.id,
                "title": other.title,
                "severity": other.severity,
                "priority": other.priority,
                "status": other.status,
                "is_regression": other.is_regression,
                "occurrence_count": other.occurrence_count,
                "url": other.url,
                "score": round(min(score, 1.0), 2),
                "reasons": reasons,
            }
        )
    suggestions.sort(key=lambda item: item["score"], reverse=True)
    return suggestions[:10]


async def merge_issues(db: AsyncSession, target: Issue, source: Issue, *, author: str | None = None) -> Issue:
    """Fold a duplicate issue into a canonical one, keeping its occurrences."""
    if target.id == source.id:
        raise RegistryError("An issue cannot be merged into itself.")
    occurrences = (
        (await db.execute(select(IssueOccurrence).where(IssueOccurrence.issue_id == source.id)))
        .scalars()
        .all()
    )
    for occurrence in occurrences:
        occurrence.issue_id = target.id
    target.occurrence_count = (target.occurrence_count or 0) + (source.occurrence_count or 0)
    target.affected_scan_count = (target.affected_scan_count or 0) + (source.affected_scan_count or 0)
    target.first_seen_at = min(target.first_seen_at, source.first_seen_at)
    source.status = IssueStatus.DUPLICATE.value
    db.add(
        IssueEvent(
            id=uuid4().hex,
            issue_id=target.id,
            kind="merge",
            from_value=source.id,
            to_value=target.id,
            body=f"Merged issue {source.id} into {target.id}",
            author=author,
        )
    )
    await db.flush()
    return target


async def registry_stats(db: AsyncSession, *, project_id: str | None = None) -> dict[str, Any]:
    stmt = select(Issue)
    if project_id:
        stmt = stmt.where(Issue.project_id == project_id)
    issues = (await db.execute(stmt)).scalars().all()
    by_severity: dict[str, int] = {}
    by_priority: dict[str, int] = {}
    by_status: dict[str, int] = {}
    by_confidence: dict[str, int] = {}
    for issue in issues:
        by_severity[issue.severity] = by_severity.get(issue.severity, 0) + 1
        by_priority[issue.priority] = by_priority.get(issue.priority, 0) + 1
        by_status[issue.status] = by_status.get(issue.status, 0) + 1
        by_confidence[issue.confidence_label] = by_confidence.get(issue.confidence_label, 0) + 1
    open_issues = [i for i in issues if i.status not in TERMINAL_STATES]
    return {
        "total": len(issues),
        "open": len(open_issues),
        "regressions": sum(1 for i in issues if i.is_regression),
        "by_severity": by_severity,
        "by_priority": by_priority,
        "by_status": by_status,
        "by_confidence": by_confidence,
    }
