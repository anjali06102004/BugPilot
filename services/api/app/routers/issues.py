from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from bugpilot_core.config import get_settings
from bugpilot_core.db.models import (
    Issue,
    IssueEvent,
    IssueEvidence,
    IssueOccurrence,
    IssueVerification,
)
from bugpilot_core.models import IssueStatus
from bugpilot_core.registry import (
    RegistryError,
    add_note,
    assign_issue,
    can_transition,
    duplicate_candidates,
    merge_issues,
    registry_stats,
    transition_issue,
)
from bugpilot_core.verification import (
    VerificationOutcome,
    verification_id,
    verify_issue,
)
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.access import assert_principal_project
from app.auth import principal_of
from app.deps import ApiError, bad_request, get_db, not_found, pagination
from app.routers.findings import evidence_url_for
from app.serializers import issue_out

router = APIRouter(tags=["issues"])

VERIFICATION_LOCK = asyncio.Semaphore(1)
VERIFICATION_TIMEOUT = 90.0

SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3, "informational": 4}
PRIORITY_ORDER = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
STATUS_ORDER = {
    IssueStatus.NEW.value: 0,
    IssueStatus.TRIAGED.value: 1,
    IssueStatus.NEEDS_REVIEW.value: 2,
    IssueStatus.CONFIRMED.value: 3,
    IssueStatus.IN_PROGRESS.value: 4,
    IssueStatus.BLOCKED.value: 5,
    IssueStatus.FIXED.value: 6,
    IssueStatus.VERIFIED.value: 7,
    IssueStatus.CLOSED.value: 8,
    IssueStatus.REOPENED.value: 9,
    IssueStatus.FALSE_POSITIVE.value: 10,
    IssueStatus.DUPLICATE.value: 11,
}


def parse_date(value: str) -> datetime:
    """Parse an ISO date or datetime, defaulting to midnight UTC."""
    text = value.strip()
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise bad_request(f"'{value}' is not a valid ISO date.") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def _date_key(value: datetime | None) -> str:
    if value is None:
        return ""
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.date().isoformat()


class UpdateIssueRequest(BaseModel):
    title: str | None = None
    summary: str | None = None
    description: str | None = None
    severity: str | None = None
    priority: str | None = None
    confidence_label: str | None = None
    status: str | None = None
    preconditions: str | None = None
    reproduction_steps: list[str] | None = None
    root_cause: str | None = None
    root_cause_status: str | None = None
    suggested_fix: str | None = None
    business_impact: str | None = None
    assigned_to: str | None = None
    labels: list[str] | None = None


class NoteRequest(BaseModel):
    body: str
    author: str | None = None


class TransitionRequest(BaseModel):
    status: str
    body: str = ""
    author: str | None = None
    force: bool = False


class AssignRequest(BaseModel):
    assignee: str | None = None
    author: str | None = None


class MergeRequest(BaseModel):
    source_issue_id: str
    author: str | None = None


@router.get("/issues")
async def list_issues(
    project_id: str | None = None,
    severity: str | None = None,
    priority: str | None = None,
    status: str | None = None,
    confidence: str | None = None,
    category: str | None = None,
    route: str | None = None,
    scan_id: str | None = None,
    assigned_to: str | None = None,
    regression: bool | None = None,
    recurring: bool | None = None,
    first_seen_after: str | None = None,
    first_seen_before: str | None = None,
    last_seen_after: str | None = None,
    last_seen_before: str | None = None,
    q: str | None = None,
    group_by: str | None = None,
    sort: str = "last_seen_at",
    order: str = "desc",
    page=Depends(pagination),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Search the registry.

    Filters are applied in SQL so `total` and pagination are always correct.
    Grouping is computed over the full filtered set, not just the current page.
    """
    filters = []
    if project_id:
        filters.append(Issue.project_id == project_id)
    if severity:
        filters.append(Issue.severity == severity)
    if priority:
        filters.append(Issue.priority == priority)
    if status:
        filters.append(Issue.status == status)
    if confidence:
        filters.append(Issue.confidence_label == confidence)
    if category:
        filters.append(Issue.category == category)
    if route:
        filters.append(Issue.route == route)
    if assigned_to:
        filters.append(Issue.assigned_to == assigned_to)
    if regression is not None:
        filters.append(Issue.is_regression == regression)
    if recurring:
        filters.append(Issue.occurrence_count > 1)
    if scan_id:
        filters.append(
            Issue.id.in_(select(IssueOccurrence.issue_id).where(IssueOccurrence.session_id == scan_id))
        )
    for value, column, is_after in (
        (first_seen_after, Issue.first_seen_at, True),
        (first_seen_before, Issue.first_seen_at, False),
        (last_seen_after, Issue.last_seen_at, True),
        (last_seen_before, Issue.last_seen_at, False),
    ):
        if value:
            parsed = parse_date(value)
            filters.append(column >= parsed if is_after else column <= parsed)
    if q:
        pattern = f"%{q.lower()}%"
        filters.append(
            func.lower(Issue.title).like(pattern)
            | func.lower(func.coalesce(Issue.summary, "")).like(pattern)
            | func.lower(func.coalesce(Issue.route, "")).like(pattern)
            | func.lower(func.coalesce(Issue.selector, "")).like(pattern)
        )

    base = select(Issue)
    count_stmt = select(func.count(Issue.id))
    for condition in filters:
        base = base.where(condition)
        count_stmt = count_stmt.where(condition)
    total = (await db.execute(count_stmt)).scalar_one()

    order_expr = {
        "severity": case(SEVERITY_ORDER, value=Issue.severity, else_=9),
        "priority": case(PRIORITY_ORDER, value=Issue.priority, else_=9),
        "status": case(STATUS_ORDER, value=Issue.status, else_=99),
        "occurrence_count": Issue.occurrence_count,
        "first_seen_at": Issue.first_seen_at,
        "last_seen_at": Issue.last_seen_at,
        "title": func.lower(Issue.title),
    }.get(sort, Issue.last_seen_at)

    if order == "asc":
        ordered = base.order_by(order_expr.asc(), Issue.last_seen_at.desc())
    else:
        ordered = base.order_by(order_expr.desc(), Issue.last_seen_at.desc())

    rows = (await db.execute(ordered.offset(page.offset).limit(page.limit))).scalars().all()

    payload: dict[str, Any] = {
        "items": [issue_out(i) for i in rows],
        "total": total,
        "sort": sort,
        "order": order,
        **page.as_dict(),
    }

    if group_by:
        allowed = {
            "severity": Issue.severity,
            "priority": Issue.priority,
            "status": Issue.status,
            "category": Issue.category,
            "project_id": Issue.project_id,
            "route": Issue.route,
            "assigned_to": Issue.assigned_to,
        }
        column = allowed.get(group_by)
        if column is None:
            raise bad_request(f"Cannot group by '{group_by}'.")
        group_stmt = select(column, func.count(Issue.id)).group_by(column)
        for condition in filters:
            group_stmt = group_stmt.where(condition)
        group_rows = (await db.execute(group_stmt)).all()
        payload["group_counts"] = {str(key or "unknown"): count for key, count in group_rows}
        all_rows = (await db.execute(base.order_by(order_expr.asc()))).scalars().all()
        groups: dict[str, list[dict[str, Any]]] = {}
        for issue in all_rows:
            key = str(getattr(issue, group_by, "unknown") or "unknown")
            bucket = groups.setdefault(key, [])
            if len(bucket) < 200:
                bucket.append(issue_out(issue))
        payload["groups"] = groups

    return payload


@router.get("/issues/trends")
async def issue_trends(
    project_id: str | None = None,
    days: int = 30,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """New, resolved and reopened issues per day, for the registry dashboard."""
    days = max(1, min(days, 180))
    since = datetime.now(UTC) - timedelta(days=days - 1)
    filters = [Issue.first_seen_at >= since]
    if project_id:
        filters.append(Issue.project_id == project_id)
    issues = (await db.execute(select(Issue).where(*filters))).scalars().all()

    issue_ids = [i.id for i in issues]
    events: list[IssueEvent] = []
    if issue_ids:
        events = (
            (
                await db.execute(
                    select(IssueEvent).where(
                        IssueEvent.issue_id.in_(issue_ids),
                        IssueEvent.created_at >= since,
                    )
                )
            )
            .scalars()
            .all()
        )

    buckets: dict[str, dict[str, int]] = {}
    for offset in range(days):
        key = (since + timedelta(days=offset)).date().isoformat()
        buckets[key] = {"new": 0, "resolved": 0, "reopened": 0}

    for issue in issues:
        if issue.first_seen_at:
            key = _date_key(issue.first_seen_at)
            if key in buckets:
                buckets[key]["new"] += 1
    for event in events:
        key = _date_key(event.created_at)
        if key not in buckets:
            continue
        if event.kind == "status_change" and event.to_value in {"fixed", "verified", "closed"}:
            buckets[key]["resolved"] += 1
        elif event.kind == "regression":
            buckets[key]["reopened"] += 1

    points = [{"date": key, **values} for key, values in buckets.items()]
    return {
        "days": days,
        "points": points,
        "totals": {
            "new": sum(p["new"] for p in points),
            "resolved": sum(p["resolved"] for p in points),
            "reopened": sum(p["reopened"] for p in points),
        },
    }


class BulkRequest(BaseModel):
    issue_ids: list[str]
    action: Literal["transition", "assign", "label"]
    status: str | None = None
    assignee: str | None = None
    labels: list[str] | None = None
    body: str = ""
    author: str | None = None


@router.post("/issues/bulk")
async def bulk_update(
    body: BulkRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Apply one triage action to many issues, reporting per-issue outcomes.

    A single invalid transition must not silently discard the rest of the batch,
    so the response distinguishes updated from failed issues.
    """
    if not body.issue_ids:
        raise bad_request("issue_ids cannot be empty.")
    if len(body.issue_ids) > 200:
        raise bad_request("A bulk operation is limited to 200 issues.")

    principal = principal_of(request)
    results: list[dict[str, Any]] = []
    updated = 0
    for issue_id in body.issue_ids:
        issue = await db.get(Issue, issue_id)
        if issue is not None:
            assert_principal_project(principal, issue.project_id)
        if issue is None:
            results.append({"id": issue_id, "ok": False, "error": "not_found"})
            continue
        try:
            if body.action == "transition":
                if not body.status:
                    raise ValueError("status is required for a transition")
                target = IssueStatus(body.status)
                if not can_transition(issue.status, target.value):
                    raise ValueError(f"invalid transition {issue.status} -> {target.value}")
                await transition_issue(db, issue, target, body=body.body, author=body.author)
            elif body.action == "assign":
                await assign_issue(db, issue, assignee=body.assignee, author=body.author)
            else:
                issue.labels = body.labels or []
                await db.flush()
            results.append({"id": issue_id, "ok": True})
            updated += 1
        except (ValueError, RegistryError) as exc:
            results.append({"id": issue_id, "ok": False, "error": str(exc)})
    await db.commit()
    return {
        "action": body.action,
        "updated": updated,
        "failed": len(results) - updated,
        "results": results,
    }


@router.get("/issues/{issue_id}/duplicates")
async def issue_duplicates(
    issue_id: str,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    issue = await db.get(Issue, issue_id)
    if not issue:
        raise not_found("Issue", issue_id)
    candidates = await duplicate_candidates(db, issue)
    return {"items": candidates, "total": len(candidates)}


class VerifyFixRequest(BaseModel):
    author: str | None = None
    body: str = ""


@router.post("/issues/{issue_id}/verify-fix")
async def verify_fix(
    issue_id: str,
    request: Request,
    body: VerifyFixRequest,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Replay the recorded reproduction and decide whether the fix holds.

    The verdict is one of `fixed`, `still_failing` or `inconclusive`. Only a
    completed replay with no matching detector signal is reported as fixed.
    """
    issue = await db.get(Issue, issue_id)
    if not issue:
        raise not_found("Issue", issue_id)

    async with VERIFICATION_LOCK:
        try:
            outcome = await asyncio.wait_for(
                verify_issue(issue, settings=get_settings(), author=body.author),
                timeout=VERIFICATION_TIMEOUT,
            )
        except TimeoutError:
            outcome = VerificationOutcome(
                verdict="inconclusive",
                method="replay",
                notes="Verification timed out before the page could be inspected.",
            )
        except Exception as exc:  # pragma: no cover - depends on the target site
            outcome = VerificationOutcome(
                verdict="inconclusive",
                method="replay",
                notes=f"Verification could not run: {exc}",
            )

    verification = IssueVerification(
        id=verification_id(),
        issue_id=issue.id,
        verdict=outcome.verdict,
        method=outcome.method,
        notes=outcome.notes,
        evidence_path=outcome.evidence_path,
        actions_replayed=outcome.actions_replayed,
        actions_failed=outcome.actions_failed,
        created_by=body.author,
    )
    db.add(verification)

    previous = issue.status
    if outcome.verdict == "fixed":
        issue.status = IssueStatus.VERIFIED.value
        issue.last_verified_at = datetime.now(UTC)
        issue.verified_count = (issue.verified_count or 0) + 1
    elif outcome.verdict == "still_failing":
        issue.status = IssueStatus.REOPENED.value
        issue.is_regression = True
        issue.reopened_count = (issue.reopened_count or 0) + 1
    else:
        issue.status = IssueStatus.NEEDS_REVIEW.value

    db.add(
        IssueEvent(
            id=verification_id(),
            issue_id=issue.id,
            kind="verification",
            from_value=previous,
            to_value=issue.status,
            body=f"{outcome.verdict}: {outcome.notes}" + (f"\n{body.body}" if body.body else ""),
            author=body.author,
        )
    )
    await db.commit()
    await db.refresh(issue)
    return {
        "verdict": outcome.verdict,
        "method": outcome.method,
        "notes": outcome.notes,
        "actions_replayed": outcome.actions_replayed,
        "actions_failed": outcome.actions_failed,
        "evidence": outcome.evidence_path,
        "issue": issue_out(issue),
    }


@router.get("/issues/{issue_id}/verifications")
async def issue_verifications(
    issue_id: str,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    issue = await db.get(Issue, issue_id)
    if not issue:
        raise not_found("Issue", issue_id)
    rows = (
        (
            await db.execute(
                select(IssueVerification)
                .where(IssueVerification.issue_id == issue_id)
                .order_by(IssueVerification.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    return {
        "items": [
            {
                "id": row.id,
                "verdict": row.verdict,
                "method": row.method,
                "notes": row.notes,
                "actions_replayed": row.actions_replayed,
                "actions_failed": row.actions_failed,
                "created_by": row.created_by,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
            for row in rows
        ],
        "total": len(rows),
    }


@router.get("/issues/stats")
async def issues_stats(
    project_id: str | None = None,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return await registry_stats(db, project_id=project_id)


@router.get("/issues/{issue_id}")
async def get_issue(
    issue_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    issue = await db.get(Issue, issue_id)
    if not issue:
        raise not_found("Issue", issue_id)
    occurrences = (
        (await db.execute(select(IssueOccurrence).where(IssueOccurrence.issue_id == issue_id)))
        .scalars()
        .all()
    )
    evidence = (
        (await db.execute(select(IssueEvidence).where(IssueEvidence.issue_id == issue_id))).scalars().all()
    )
    events = (
        (
            await db.execute(
                select(IssueEvent).where(IssueEvent.issue_id == issue_id).order_by(IssueEvent.created_at)
            )
        )
        .scalars()
        .all()
    )
    verifications = (
        (
            await db.execute(
                select(IssueVerification)
                .where(IssueVerification.issue_id == issue_id)
                .order_by(IssueVerification.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    return issue_out(
        issue,
        occurrences=occurrences,
        evidence=evidence,
        events=events,
        verifications=verifications,
        evidence_url=lambda path: evidence_url_for(request, path),
    )


@router.patch("/issues/{issue_id}")
async def update_issue(
    issue_id: str,
    body: UpdateIssueRequest,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    issue = await db.get(Issue, issue_id)
    if not issue:
        raise not_found("Issue", issue_id)
    for field in (
        "title",
        "summary",
        "description",
        "severity",
        "priority",
        "confidence_label",
        "preconditions",
        "root_cause",
        "root_cause_status",
        "suggested_fix",
        "business_impact",
        "assigned_to",
    ):
        value = getattr(body, field)
        if value is not None:
            setattr(issue, field, value)
    if body.reproduction_steps is not None:
        issue.reproduction_steps = body.reproduction_steps
    if body.labels is not None:
        issue.labels = body.labels
    if body.status is not None:
        try:
            target = IssueStatus(body.status)
        except ValueError as exc:
            raise bad_request(f"Unknown status '{body.status}'.") from exc
        if not can_transition(issue.status, target.value):
            raise ApiError(
                409,
                "invalid_transition",
                f"Cannot move an issue from '{issue.status}' to '{target.value}'.",
            )
        await transition_issue(db, issue, target, force=True)
    await db.commit()
    await db.refresh(issue)
    return issue_out(issue)


@router.post("/issues/{issue_id}/notes")
async def create_note(
    issue_id: str,
    body: NoteRequest,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    issue = await db.get(Issue, issue_id)
    if not issue:
        raise not_found("Issue", issue_id)
    if not body.body.strip():
        raise bad_request("A note cannot be empty.")
    event = await add_note(db, issue, body=body.body, author=body.author)
    await db.commit()
    await db.refresh(event)
    return {
        "id": event.id,
        "issue_id": issue.id,
        "kind": event.kind,
        "body": event.body,
        "author": event.author,
        "created_at": event.created_at.isoformat() if event.created_at else None,
    }


@router.post("/issues/{issue_id}/assign")
async def assign(
    issue_id: str,
    body: AssignRequest,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    issue = await db.get(Issue, issue_id)
    if not issue:
        raise not_found("Issue", issue_id)
    await assign_issue(db, issue, assignee=body.assignee, author=body.author)
    await db.commit()
    await db.refresh(issue)
    return issue_out(issue)


@router.post("/issues/{issue_id}/transition")
async def transition(
    issue_id: str,
    body: TransitionRequest,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    issue = await db.get(Issue, issue_id)
    if not issue:
        raise not_found("Issue", issue_id)
    try:
        target = IssueStatus(body.status)
    except ValueError as exc:
        raise bad_request(f"Unknown status '{body.status}'.") from exc
    if not can_transition(issue.status, target.value) and not body.force:
        raise ApiError(
            409,
            "invalid_transition",
            f"Cannot move an issue from '{issue.status}' to '{target.value}'.",
            {"allowed": sorted(allowed_targets(issue.status))},
        )
    await transition_issue(db, issue, target, body=body.body, author=body.author, force=body.force)
    await db.commit()
    await db.refresh(issue)
    return issue_out(issue)


def allowed_targets(status: str) -> set[str]:
    from bugpilot_core.registry import ALLOWED_TRANSITIONS

    return {s.value for s in ALLOWED_TRANSITIONS.get(status, set())}


@router.post("/issues/{issue_id}/merge")
async def merge(
    issue_id: str,
    body: MergeRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    target = await db.get(Issue, issue_id)
    if not target:
        raise not_found("Issue", issue_id)
    source = await db.get(Issue, body.source_issue_id)
    if not source:
        raise not_found("Issue", body.source_issue_id)
    principal = principal_of(request)
    assert_principal_project(principal, target.project_id)
    assert_principal_project(principal, source.project_id)
    try:
        await merge_issues(db, target, source, author=body.author)
    except ValueError as exc:
        raise bad_request(str(exc)) from exc
    await db.commit()
    await db.refresh(target)
    return issue_out(target)
