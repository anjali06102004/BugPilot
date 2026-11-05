"""Response serializers. Keeping them in one place keeps the API shape stable
for the dashboard, the browser extension and the report exporters."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from bugpilot_core.db.models import (
    ActionRecord,
    Finding,
    Issue,
    IssueEvent,
    IssueEvidence,
    IssueOccurrence,
    IssueVerification,
    PageRecord,
    Project,
    TestSession,
)
from bugpilot_core.scope import scope_summary


def project_out(project: Project) -> dict[str, Any]:
    return {
        "id": project.id,
        "name": project.name,
        "website_url": project.website_url,
        "environment": project.environment,
        "description": project.description,
        "critical_routes": project.critical_routes or [],
        "evidence_retention_days": project.evidence_retention_days,
        "created_at": project.created_at.isoformat() if project.created_at else None,
    }


def scope_out(session: TestSession) -> dict[str, Any]:
    scope = session.scope_json or {}
    summary = None
    if scope:
        try:
            from bugpilot_core.models import ScanScope

            summary = scope_summary(ScanScope.model_validate(scope))
        except Exception:
            summary = None
    return {
        "type": session.scope_type,
        "summary": summary or session.scope_type,
        "definition": scope,
    }


def scan_out(session: TestSession) -> dict[str, Any]:
    return {
        "id": session.id,
        "project_id": session.project_id,
        "start_url": session.start_url,
        "status": session.status,
        "scope": scope_out(session),
        "error_message": session.error_message,
        "stop_reason": session.stop_reason,
        "pages_tested": session.pages_tested,
        "pages_skipped": session.pages_skipped,
        "actions_taken": session.actions_taken,
        "model_calls": session.model_calls,
        "config": session.config_json,
        "created_at": session.created_at.isoformat() if session.created_at else None,
        "started_at": session.started_at.isoformat() if session.started_at else None,
        "completed_at": session.completed_at.isoformat() if session.completed_at else None,
    }


def page_out(page: PageRecord, *, screenshot_url: str | None = None) -> dict[str, Any]:
    return {
        "id": page.id,
        "url": page.url,
        "title": page.title,
        "viewport_name": page.viewport_name,
        "in_scope": page.in_scope,
        "skip_reason": page.skip_reason,
        "screenshot": screenshot_url,
        "screenshot_path": page.screenshot_path,
        "created_at": page.created_at.isoformat() if page.created_at else None,
    }


def action_out(action: ActionRecord) -> dict[str, Any]:
    return {
        "id": action.id,
        "type": action.type,
        "description": action.description,
        "selector": action.selector,
        "url": action.url,
        "blocked": bool(action.blocked),
        "block_reason": action.block_reason,
        "created_at": action.created_at.isoformat() if action.created_at else None,
    }


def finding_out(finding: Finding, *, evidence_url: str | None = None) -> dict[str, Any]:
    extra = finding.extra if isinstance(finding.extra, dict) else {}
    return {
        "id": finding.id,
        "issue_id": finding.issue_id,
        "session_id": finding.session_id,
        "category": finding.category,
        "title": finding.title,
        "description": finding.description,
        "severity": finding.severity,
        "priority": finding.priority,
        "confidence": finding.confidence,
        "confidence_label": finding.confidence_label,
        "status": finding.status,
        "source": finding.source,
        "url": finding.url,
        "route": finding.route,
        "component": finding.component,
        "selector": finding.selector,
        "expected": finding.expected,
        "actual": finding.actual,
        "steps": finding.steps_json or [],
        "suggested_fix": finding.suggested_fix,
        "root_cause": finding.root_cause,
        "reproduced_count": finding.reproduced_count,
        "verification_attempts": finding.verification_attempts,
        "screenshot": evidence_url,
        "screenshot_path": finding.screenshot_path,
        "viewport": extra.get("viewport"),
        "priority_rationale": extra.get("priority_rationale", []),
        "reproduced": bool(extra.get("reproduced")),
        "created_at": finding.created_at.isoformat() if finding.created_at else None,
    }


def occurrence_out(occurrence: IssueOccurrence) -> dict[str, Any]:
    return {
        "id": occurrence.id,
        "issue_id": occurrence.issue_id,
        "session_id": occurrence.session_id,
        "finding_id": occurrence.finding_id,
        "url": occurrence.url,
        "route": occurrence.route,
        "viewport": occurrence.viewport,
        "severity": occurrence.severity,
        "priority": occurrence.priority,
        "confidence": occurrence.confidence,
        "confidence_label": occurrence.confidence_label,
        "verified": occurrence.verified,
        "reproduced": occurrence.reproduced,
        "notes": occurrence.notes,
        "created_at": occurrence.created_at.isoformat() if occurrence.created_at else None,
    }


def evidence_out(item: IssueEvidence, *, evidence_url: str | None = None) -> dict[str, Any]:
    return {
        "id": item.id,
        "kind": item.kind,
        "path": item.path,
        "url": evidence_url,
        "content": item.content,
        "redacted": item.redacted,
        "created_at": item.created_at.isoformat() if item.created_at else None,
    }


def event_out(event) -> dict[str, Any]:
    return event.model_dump(mode="json")


def issue_out(
    issue: Issue,
    *,
    occurrences: list[IssueOccurrence] | None = None,
    evidence: list[IssueEvidence] | None = None,
    events: list[IssueEvent] | None = None,
    verifications: list[IssueVerification] | None = None,
    evidence_url: Callable[[str | None], str | None] | None = None,
) -> dict[str, Any]:
    extra = issue.extra if isinstance(issue.extra, dict) else {}
    payload = {
        "id": issue.id,
        "issue_key": issue.issue_key,
        "project_id": issue.project_id,
        "title": issue.title,
        "summary": issue.summary,
        "description": issue.description,
        "category": issue.category,
        "severity": issue.severity,
        "priority": issue.priority,
        "confidence": issue.confidence,
        "confidence_label": issue.confidence_label,
        "status": issue.status,
        "source": issue.source,
        "url": issue.url,
        "route": issue.route,
        "component": issue.component,
        "selector": issue.selector,
        "expected": issue.expected,
        "actual": issue.actual,
        "preconditions": issue.preconditions,
        "reproduction_steps": issue.reproduction_steps or [],
        "root_cause": issue.root_cause,
        "root_cause_status": issue.root_cause_status,
        "suggested_fix": issue.suggested_fix,
        "business_impact": issue.business_impact,
        "environment": issue.environment,
        "browser": issue.browser,
        "viewport": issue.viewport,
        "assigned_to": issue.assigned_to,
        "labels": issue.labels or [],
        "is_regression": issue.is_regression,
        "occurrence_count": issue.occurrence_count,
        "affected_scan_count": issue.affected_scan_count,
        "affected_page_count": issue.affected_page_count,
        "verified_count": issue.verified_count,
        "reopened_count": issue.reopened_count,
        "priority_rationale": extra.get("priority_rationale", []),
        "first_seen_at": issue.first_seen_at.isoformat() if issue.first_seen_at else None,
        "last_seen_at": issue.last_seen_at.isoformat() if issue.last_seen_at else None,
        "last_verified_at": issue.last_verified_at.isoformat() if issue.last_verified_at else None,
        "created_at": issue.created_at.isoformat() if issue.created_at else None,
        "updated_at": issue.updated_at.isoformat() if issue.updated_at else None,
    }
    if occurrences is not None:
        payload["occurrences"] = [occurrence_out(o) for o in occurrences]
    if evidence is not None:
        payload["evidence"] = [
            evidence_out(e, evidence_url=evidence_url(e.path) if evidence_url else None) for e in evidence
        ]
    if verifications is not None:
        payload["verifications"] = [
            {
                "id": v.id,
                "verdict": v.verdict,
                "method": v.method,
                "notes": v.notes,
                "actions_replayed": v.actions_replayed,
                "actions_failed": v.actions_failed,
                "created_by": v.created_by,
                "created_at": v.created_at.isoformat() if v.created_at else None,
            }
            for v in verifications
        ]
    if events is not None:
        payload["events"] = [
            {
                "id": e.id,
                "kind": e.kind,
                "from_value": e.from_value,
                "to_value": e.to_value,
                "body": e.body,
                "author": e.author,
                "created_at": e.created_at.isoformat() if e.created_at else None,
            }
            for e in events
        ]
    return payload
