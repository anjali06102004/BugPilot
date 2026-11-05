"""Report generation.

Reports are built from what is actually stored: the scan, its pages, the
findings, the canonical registry issues and their evidence. Nothing here
contains example or placeholder content.
"""

from __future__ import annotations

import io
import json
import zipfile
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bugpilot_core.db.models import (
    Finding,
    FindingEvidence,
    Issue,
    IssueEvidence,
    IssueOccurrence,
    PageRecord,
    Project,
    TestSession,
)
from bugpilot_core.evidence import EvidenceStore
from bugpilot_core.registry import TERMINAL_STATES
from bugpilot_core.scope import scope_summary

SEVERITY_ORDER = ["critical", "high", "medium", "low", "informational"]
PRIORITY_ORDER = ["P0", "P1", "P2", "P3"]


def issue_dict(
    issue: Issue, occurrence_rows: list[IssueOccurrence], evidence: list[IssueEvidence]
) -> dict[str, Any]:
    """One issue as it appears in every export."""
    issue_occurrences = [o for o in occurrence_rows if o.issue_id == issue.id]
    issue_evidence = [e for e in evidence if e.issue_id == issue.id]
    return {
        "id": issue.id,
        "title": issue.title,
        "summary": issue.summary,
        "description": issue.description,
        "category": issue.category,
        "severity": issue.severity,
        "priority": issue.priority,
        "confidence_label": issue.confidence_label,
        "status": issue.status,
        "url": issue.url,
        "route": issue.route,
        "component": issue.component,
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
        "first_seen_at": issue.first_seen_at.isoformat() if issue.first_seen_at else None,
        "last_seen_at": issue.last_seen_at.isoformat() if issue.last_seen_at else None,
        "last_verified_at": issue.last_verified_at.isoformat() if issue.last_verified_at else None,
        "occurrences": [
            {
                "id": o.id,
                "session_id": o.session_id,
                "url": o.url,
                "viewport": o.viewport,
                "verified": o.verified,
                "reproduced": o.reproduced,
                "confidence": o.confidence,
                "confidence_label": o.confidence_label,
                "created_at": o.created_at.isoformat() if o.created_at else None,
            }
            for o in issue_occurrences
        ],
        "evidence": [
            {
                "id": e.id,
                "kind": e.kind,
                "path": e.path,
                "content": e.content,
                "redacted": e.redacted,
                "created_at": e.created_at.isoformat() if e.created_at else None,
            }
            for e in issue_evidence
        ],
    }


async def collect_project_report(db: AsyncSession, project: Project) -> dict[str, Any]:
    """Project-level report built from the registry, not from one scan."""
    issues = (await db.execute(select(Issue).where(Issue.project_id == project.id))).scalars().all()
    issue_ids = [i.id for i in issues]
    occurrence_rows: list[IssueOccurrence] = []
    evidence: list[IssueEvidence] = []
    if issue_ids:
        occurrence_rows = list(
            (await db.execute(select(IssueOccurrence).where(IssueOccurrence.issue_id.in_(issue_ids))))
            .scalars()
            .all()
        )
        evidence = list(
            (await db.execute(select(IssueEvidence).where(IssueEvidence.issue_id.in_(issue_ids))))
            .scalars()
            .all()
        )
    scans = (
        (
            await db.execute(
                select(TestSession)
                .where(TestSession.project_id == project.id)
                .order_by(TestSession.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    issues_payload = [issue_dict(issue, occurrence_rows, evidence) for issue in issues]
    severity_counts: dict[str, int] = {}
    priority_counts: dict[str, int] = {}
    for issue in issues_payload:
        severity_counts[issue["severity"]] = severity_counts.get(issue["severity"], 0) + 1
        priority_counts[issue["priority"]] = priority_counts.get(issue["priority"], 0) + 1
    open_issues = [i for i in issues_payload if i["status"] not in TERMINAL_STATES]
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "scan": {
            "id": f"project:{project.id}",
            "start_url": project.website_url,
            "status": "project",
            "scope_type": "project",
            "scope": {},
            "scope_summary": f"All recorded scans for {project.name}",
            "pages_tested": sum(s.pages_tested or 0 for s in scans),
            "actions_taken": sum(s.actions_taken or 0 for s in scans),
            "pages_skipped": sum(s.pages_skipped or 0 for s in scans),
            "model_calls": sum(s.model_calls or 0 for s in scans),
            "stop_reason": f"{len(scans)} scan(s) recorded",
            "error_message": None,
            "created_at": min((s.created_at for s in scans if s.created_at), default=None),
            "completed_at": max((s.completed_at for s in scans if s.completed_at), default=None),
        },
        "project": {
            "id": project.id,
            "name": project.name,
            "website_url": project.website_url,
            "environment": project.environment,
            "critical_routes": project.critical_routes or [],
        },
        "pages": [],
        "findings": [],
        "issues": issues_payload,
        "finding_evidence": [],
        "stats": {
            "total_issues": len(issues_payload),
            "open_issues": len(open_issues),
            "regressions": sum(1 for i in issues_payload if i["is_regression"]),
            "by_severity": severity_counts,
            "by_priority": priority_counts,
            "confirmed": sum(1 for i in issues_payload if i["confidence_label"] == "confirmed"),
        },
        "scans": [
            {
                "id": s.id,
                "url": s.start_url,
                "status": s.status,
                "pages_tested": s.pages_tested,
                "actions_taken": s.actions_taken,
                "created_at": s.created_at.isoformat() if s.created_at else None,
            }
            for s in scans
        ],
    }


def render_issue_markdown(issue: dict[str, Any]) -> str:
    """Single-issue export for a tracker or a hand-off document."""
    lines = [
        f"# {issue['title']}",
        "",
        f"- **Issue id:** `{issue['id']}`",
        f"- **Category:** {issue['category']}",
        f"- **Severity / priority:** {issue['severity']} / {issue['priority']}",
        f"- **Confidence:** {issue['confidence_label']}",
        f"- **Status:** {issue['status']}",
        f"- **URL:** {issue['url']}",
    ]
    for label, key in (
        ("Route", "route"),
        ("Component", "component"),
        ("Environment", "environment"),
        ("Browser", "browser"),
        ("Viewport", "viewport"),
        ("First detected", "first_seen_at"),
        ("Last detected", "last_seen_at"),
        ("Occurrences", "occurrence_count"),
        ("Owner", "assigned_to"),
    ):
        if issue.get(key):
            lines.append(f"- **{label}:** {issue[key]}")
    if issue.get("is_regression"):
        lines.append("- **Regression:** reopened after being resolved")
    lines.append("")

    for title, key in (
        ("Summary", "summary"),
        ("Technical explanation", "description"),
        ("User and business impact", "business_impact"),
        ("Expected behaviour", "expected"),
        ("Observed behaviour", "actual"),
        ("Preconditions", "preconditions"),
        ("Suggested fix", "suggested_fix"),
    ):
        if issue.get(key):
            lines += [f"## {title}", "", str(issue[key]), ""]

    if issue.get("reproduction_steps"):
        lines += ["## Reproduction steps", ""]
        for index, step in enumerate(issue["reproduction_steps"], start=1):
            lines.append(f"{index}. {step}")
        lines.append("")

    if issue.get("root_cause"):
        marker = "confirmed" if issue.get("root_cause_status") == "confirmed" else "unconfirmed"
        lines += [f"## Root cause ({marker})", "", issue["root_cause"], ""]

    if issue.get("occurrences"):
        lines += ["## Occurrence history", ""]
        for occurrence in issue["occurrences"]:
            lines.append(
                f"- {occurrence['created_at']} on `{occurrence['url']}` "
                f"({occurrence['confidence_label']}, verified: "
                f"{'yes' if occurrence['verified'] else 'no'})"
            )
        lines.append("")

    lines += [
        "---",
        "Generated by BugPilot. Root causes are hypotheses unless marked confirmed.",
        "",
    ]
    return "\n".join(lines)


async def collect_scan_report(db: AsyncSession, session: TestSession) -> dict[str, Any]:
    project = await db.get(Project, session.project_id)
    findings = (await db.execute(select(Finding).where(Finding.session_id == session.id))).scalars().all()
    pages = (await db.execute(select(PageRecord).where(PageRecord.session_id == session.id))).scalars().all()
    issues = (
        (await db.execute(select(Issue).where(Issue.id.in_([f.issue_id for f in findings if f.issue_id]))))
        .scalars()
        .all()
    )
    issue_ids = [i.id for i in issues]
    occurrences = (
        await db.execute(select(IssueOccurrence).where(IssueOccurrence.issue_id.in_(issue_ids)))
        if issue_ids
        else None
    )
    occurrence_rows = list(occurrences.scalars().all()) if occurrences is not None else []
    evidence_rows = (
        await db.execute(select(IssueEvidence).where(IssueEvidence.issue_id.in_(issue_ids)))
        if issue_ids
        else None
    )
    evidence = list(evidence_rows.scalars().all()) if evidence_rows is not None else []
    finding_evidence = (
        (
            await db.execute(
                select(FindingEvidence).where(FindingEvidence.finding_id.in_([f.id for f in findings]))
            )
        )
        .scalars()
        .all()
    )

    scope = session.scope_json or {}
    issues_payload = [issue_dict(issue, occurrence_rows, evidence) for issue in issues]

    severity_counts: dict[str, int] = {}
    priority_counts: dict[str, int] = {}
    for issue in issues_payload:
        severity_counts[issue["severity"]] = severity_counts.get(issue["severity"], 0) + 1
        priority_counts[issue["priority"]] = priority_counts.get(issue["priority"], 0) + 1

    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "scan": {
            "id": session.id,
            "start_url": session.start_url,
            "status": session.status,
            "scope_type": session.scope_type,
            "scope": scope,
            "scope_summary": scope_summary(_scope_model(scope, session.start_url))
            if scope
            else session.scope_type,
            "pages_tested": session.pages_tested,
            "actions_taken": session.actions_taken,
            "pages_skipped": session.pages_skipped,
            "model_calls": session.model_calls,
            "stop_reason": session.stop_reason,
            "error_message": session.error_message,
            "created_at": session.created_at.isoformat() if session.created_at else None,
            "completed_at": session.completed_at.isoformat() if session.completed_at else None,
        },
        "project": {
            "id": project.id if project else None,
            "name": project.name if project else None,
            "website_url": project.website_url if project else None,
            "environment": project.environment if project else None,
            "critical_routes": project.critical_routes if project else [],
        },
        "pages": [
            {
                "url": p.url,
                "title": p.title,
                "viewport": p.viewport_name,
                "screenshot_path": p.screenshot_path,
            }
            for p in pages
        ],
        "findings": [
            {
                "id": f.id,
                "issue_id": f.issue_id,
                "title": f.title,
                "category": f.category,
                "severity": f.severity,
                "priority": f.priority,
                "confidence": f.confidence,
                "confidence_label": f.confidence_label,
                "status": f.status,
                "source": f.source,
                "url": f.url,
                "route": f.route,
                "selector": f.selector,
                "expected": f.expected,
                "actual": f.actual,
                "steps": f.steps_json or [],
                "suggested_fix": f.suggested_fix,
                "root_cause": f.root_cause,
                "reproduced_count": f.reproduced_count,
                "verification_attempts": f.verification_attempts,
                "screenshot_path": f.screenshot_path,
                "created_at": f.created_at.isoformat() if f.created_at else None,
            }
            for f in findings
        ],
        "issues": issues_payload,
        "finding_evidence": [
            {
                "finding_id": e.finding_id,
                "kind": e.kind,
                "path": e.path,
                "content": e.content,
            }
            for e in finding_evidence
        ],
        "stats": {
            "total_issues": len(issues_payload),
            "open_issues": sum(1 for i in issues_payload if i["status"] not in TERMINAL_STATES),
            "regressions": sum(1 for i in issues_payload if i["is_regression"]),
            "by_severity": severity_counts,
            "by_priority": priority_counts,
            "confirmed": sum(1 for i in issues_payload if i["confidence_label"] == "confirmed"),
        },
    }


def _scope_model(scope: dict[str, Any], start_url: str):
    from bugpilot_core.models import ScanScope

    data = dict(scope)
    data.setdefault("start_url", start_url)
    return ScanScope.model_validate(data)


def _group(issues: list[dict[str, Any]], key: str, order: list[str]) -> list[tuple[str, list]]:
    grouped: dict[str, list] = {name: [] for name in order}
    for issue in issues:
        value = issue.get(key) or "unknown"
        grouped.setdefault(value, []).append(issue)
    return [(name, items) for name, items in grouped.items() if items]


def render_finding_markdown(finding: dict[str, Any], issue: dict[str, Any] | None = None) -> str:
    """A single-finding export for pasting into an issue tracker."""
    source = issue or finding
    lines = [
        f"# {source.get('title') or finding.get('title')}",
        "",
        f"- **Finding id:** `{finding.get('id')}`",
    ]
    if issue:
        lines.append(f"- **Registry issue:** `{issue.get('id')}`")
    lines += [
        f"- **Category:** {finding.get('category')}",
        f"- **Severity / priority:** {finding.get('severity')} / {finding.get('priority')}",
        f"- **Confidence:** {finding.get('confidence_label')}",
        f"- **Status:** {finding.get('status')}",
        f"- **URL:** {finding.get('url')}",
    ]
    if finding.get("route"):
        lines.append(f"- **Route:** {finding.get('route')}")
    if finding.get("viewport"):
        lines.append(f"- **Viewport:** {finding.get('viewport')}")
    if finding.get("created_at"):
        lines.append(f"- **Detected:** {finding.get('created_at')}")
    lines.append("")

    if source.get("summary"):
        lines += ["## Summary", "", source["summary"], ""]
    if source.get("description") or finding.get("description"):
        lines += ["## Technical explanation", "", source.get("description") or finding.get("description"), ""]
    if source.get("expected") or finding.get("expected"):
        lines += ["## Expected behaviour", "", source.get("expected") or finding.get("expected"), ""]
    if source.get("actual") or finding.get("actual"):
        lines += ["## Observed behaviour", "", source.get("actual") or finding.get("actual"), ""]

    steps = source.get("reproduction_steps") or finding.get("steps") or []
    if steps:
        lines += ["## Reproduction steps", ""]
        for index, step in enumerate(steps, start=1):
            lines.append(f"{index}. {step}")
        lines.append("")

    root_cause = source.get("root_cause") or finding.get("root_cause")
    if root_cause:
        marker = "confirmed" if source.get("root_cause_status") == "confirmed" else "unconfirmed"
        lines += [f"## Root cause ({marker})", "", root_cause, ""]
    fix = source.get("suggested_fix") or finding.get("suggested_fix")
    if fix:
        lines += ["## Suggested fix", "", fix, ""]

    if finding.get("screenshot"):
        lines += ["## Evidence", "", f"- Screenshot: `{finding['screenshot']}`", ""]
    lines += [
        "---",
        "Generated by BugPilot. Root causes are hypotheses unless marked confirmed.",
        "",
    ]
    return "\n".join(lines)


def render_markdown(data: dict[str, Any]) -> str:
    scan = data["scan"]
    project = data["project"]
    stats = data["stats"]
    issues = data["issues"]
    lines: list[str] = []

    lines += ["# BugPilot report", ""]
    lines += [
        f"- **Project:** {project.get('name') or '—'}",
        f"- **Target:** {scan.get('start_url')}",
        f"- **Scan scope:** {scan.get('scope_summary') or scan.get('scope_type')}",
        f"- **Status:** {scan.get('status')}",
        f"- **Pages inspected:** {scan.get('pages_tested')}",
        f"- **Pages skipped:** {scan.get('pages_skipped')}",
        f"- **Actions performed:** {scan.get('actions_taken')}",
        f"- **Generated:** {data['generated_at']}",
        "",
    ]

    lines += ["## Executive summary", ""]
    if not issues:
        lines += [
            "No issues were recorded during this scan. The inspected scope was covered "
            "by the deterministic detectors that were enabled.",
            "",
        ]
    else:
        lines += [
            f"{stats['total_issues']} distinct issue(s) were identified, "
            f"{stats['open_issues']} still open, {stats['confirmed']} confirmed by evidence. "
            f"{stats['regressions']} regression(s) detected."
            "",
        ]
        for severity, items in _group(issues, "severity", SEVERITY_ORDER):
            lines.append(f"- **{severity}**: {len(items)}")
        lines.append("")

    lines += ["## Coverage and limitations", ""]
    if scan.get("stop_reason"):
        lines.append(f"- The scan stopped because: {scan.get('stop_reason')}.")
    if scan.get("error_message"):
        lines.append(f"- The scan reported an error: {scan.get('error_message')}.")
    lines += [
        "- This report covers only the pages and elements listed below. It is not a "
        "statement that the application is free of other defects.",
        "- Root causes marked *unconfirmed* are hypotheses produced by the analysis "
        "layer and require engineering review.",
        "",
    ]

    if data.get("pages"):
        lines += ["### Pages inspected", ""]
        for page in data["pages"]:
            lines.append(f"- `{page['url']}` ({page['viewport']})")
        lines.append("")

    if issues:
        lines += ["## Findings by priority", ""]
        for priority, items in _group(issues, "priority", PRIORITY_ORDER):
            lines += [f"### {priority}", ""]
            for issue in items:
                lines.append(
                    f"- **{issue['title']}** — {issue['severity']} / {issue['priority']} "
                    f"({issue['confidence_label']})"
                )
            lines.append("")

        lines += ["## Findings by severity", ""]
        for severity, items in _group(issues, "severity", SEVERITY_ORDER):
            lines += [f"### {severity}", ""]
            for issue in items:
                lines.append(
                    f"- **{issue['title']}** — {issue['priority']} · {issue['category']} · {issue['url']}"
                )
            lines.append("")

        lines += ["## Detailed bug records", ""]
        for issue in issues:
            lines += [f"### {issue['title']}", ""]
            lines += [
                f"- **Issue id:** `{issue['id']}`",
                f"- **Severity:** {issue['severity']}",
                f"- **Priority:** {issue['priority']}",
                f"- **Confidence:** {issue['confidence_label']}",
                f"- **Status:** {issue['status']}",
                f"- **Category:** {issue['category']}",
                f"- **URL:** {issue['url']}",
            ]
            if issue.get("route"):
                lines.append(f"- **Route:** {issue['route']}")
            if issue.get("component"):
                lines.append(f"- **Component:** {issue['component']}")
            if issue.get("environment"):
                lines.append(f"- **Environment:** {issue['environment']}")
            if issue.get("browser"):
                lines.append(f"- **Browser:** {issue['browser']}")
            if issue.get("viewport"):
                lines.append(f"- **Viewport:** {issue['viewport']}")
            if issue.get("first_seen_at"):
                lines.append(f"- **First detected:** {issue['first_seen_at']}")
            if issue.get("last_seen_at"):
                lines.append(f"- **Last detected:** {issue['last_seen_at']}")
            if issue.get("occurrence_count"):
                lines.append(f"- **Occurrences:** {issue['occurrence_count']}")
            if issue.get("is_regression"):
                lines.append("- **Regression:** yes, this issue reappeared after being resolved")
            if issue.get("assigned_to"):
                lines.append(f"- **Owner:** {issue['assigned_to']}")
            lines.append("")

            if issue.get("summary"):
                lines += ["**Summary**", "", issue["summary"], ""]
            if issue.get("description"):
                lines += ["**Technical explanation**", "", issue["description"], ""]
            if issue.get("business_impact"):
                lines += ["**User and business impact**", "", issue["business_impact"], ""]
            if issue.get("expected"):
                lines += ["**Expected behaviour**", "", issue["expected"], ""]
            if issue.get("actual"):
                lines += ["**Observed behaviour**", "", issue["actual"], ""]
            if issue.get("preconditions"):
                lines += ["**Preconditions**", "", issue["preconditions"], ""]
            if issue.get("reproduction_steps"):
                lines += ["**Reproduction steps**", ""]
                for index, step in enumerate(issue["reproduction_steps"], start=1):
                    lines.append(f"{index}. {step}")
                lines.append("")
            if issue.get("root_cause"):
                marker = "confirmed" if issue.get("root_cause_status") == "confirmed" else "unconfirmed"
                lines += [f"**Root cause ({marker})**", "", issue["root_cause"], ""]
            if issue.get("suggested_fix"):
                lines += ["**Suggested fix**", "", issue["suggested_fix"], ""]

            if issue.get("evidence"):
                lines += ["**Evidence**", ""]
                for item in issue["evidence"]:
                    detail = f" — `{item['path']}`" if item.get("path") else ""
                    lines.append(f"- {item['kind']}{detail}")
                lines.append("")

            if issue.get("occurrences"):
                lines += ["**Occurrence history**", ""]
                for occ in issue["occurrences"]:
                    lines.append(
                        f"- {occ['created_at']} on `{occ['url']}` "
                        f"({occ['confidence_label']}, verified: {'yes' if occ['verified'] else 'no'})"
                    )
                lines.append("")

    lines += ["## Summary statistics", ""]
    lines += [
        f"- Total issues: {stats['total_issues']}",
        f"- Open issues: {stats['open_issues']}",
        f"- Confirmed: {stats['confirmed']}",
        f"- Regressions: {stats['regressions']}",
    ]
    for severity, count in sorted(stats["by_severity"].items()):
        lines.append(f"- {severity}: {count}")
    lines.append("")
    return "\n".join(lines)


def render_pdf(data: dict[str, Any], evidence_store: EvidenceStore | None = None) -> bytes:
    """Render the report to PDF. Falls back to a plain-text PDF if reportlab
    is not installed rather than failing the whole export."""
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.lib.units import mm
        from reportlab.platypus import (
            Image,
            PageBreak,
            Paragraph,
            SimpleDocTemplate,
            Spacer,
            Table,
            TableStyle,
        )
    except ImportError:  # pragma: no cover - optional dependency
        return _render_plain_pdf(render_markdown(data))

    styles = getSampleStyleSheet()
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=16 * mm,
        bottomMargin=16 * mm,
        title="BugPilot report",
    )
    story: list[Any] = []

    def h(text: str, level: int = 1):
        return Paragraph(text, styles[f"Heading{level}"])

    def p(text: str):
        return Paragraph(_escape(text), styles["BodyText"])

    story.append(h("BugPilot report"))
    story.append(Spacer(1, 6))
    scan = data["scan"]
    project = data["project"]
    meta = [
        ["Project", project.get("name") or "-"],
        ["Target", scan.get("start_url") or "-"],
        ["Scope", scan.get("scope_summary") or scan.get("scope_type") or "-"],
        ["Status", scan.get("status") or "-"],
        ["Pages inspected", str(scan.get("pages_tested", 0))],
        ["Pages skipped", str(scan.get("pages_skipped", 0))],
        ["Actions performed", str(scan.get("actions_taken", 0))],
        ["Generated", data["generated_at"]],
    ]
    table = Table(meta, colWidths=[45 * mm, 125 * mm])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f3f4f6")),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#d1d5db")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("FONTSIZE", (0, 0), (-1, -1), 8.5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    story.append(table)
    story.append(Spacer(1, 10))

    stats = data["stats"]
    story.append(h("Executive summary", 2))
    story.append(
        p(
            f"{stats['total_issues']} distinct issue(s) identified, "
            f"{stats['open_issues']} open, {stats['confirmed']} confirmed, "
            f"{stats['regressions']} regression(s)."
        )
    )
    story.append(Spacer(1, 6))
    if stats["by_severity"]:
        sev_rows = [["Severity", "Count"]] + [
            [name, str(count)] for name, count in sorted(stats["by_severity"].items())
        ]
        sev_table = Table(sev_rows, colWidths=[60 * mm, 30 * mm])
        sev_table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#111827")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#d1d5db")),
                    ("FONTSIZE", (0, 0), (-1, -1), 8.5),
                ]
            )
        )
        story.append(sev_table)
    story.append(Spacer(1, 10))

    story.append(h("Detailed bug records", 2))
    for issue in data["issues"]:
        story.append(h(_escape(issue["title"]), 3))
        rows = [
            ["Severity", issue["severity"]],
            ["Priority", issue["priority"]],
            ["Confidence", issue["confidence_label"]],
            ["Status", issue["status"]],
            ["Category", issue["category"]],
            ["URL", issue["url"]],
        ]
        if issue.get("route"):
            rows.append(["Route", issue["route"]])
        if issue.get("first_seen_at"):
            rows.append(["First detected", issue["first_seen_at"]])
        if issue.get("last_seen_at"):
            rows.append(["Last detected", issue["last_seen_at"]])
        if issue.get("occurrence_count"):
            rows.append(["Occurrences", str(issue["occurrence_count"])])
        issue_table = Table(rows, colWidths=[35 * mm, 135 * mm])
        issue_table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f3f4f6")),
                    ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#d1d5db")),
                    ("FONTSIZE", (0, 0), (-1, -1), 8),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ]
            )
        )
        story.append(issue_table)
        story.append(Spacer(1, 4))
        for label, value in [
            ("Summary", issue.get("summary")),
            ("Expected", issue.get("expected")),
            ("Observed", issue.get("actual")),
            ("Root cause", issue.get("root_cause")),
            ("Suggested fix", issue.get("suggested_fix")),
        ]:
            if value:
                story.append(Paragraph(f"<b>{label}:</b> " + _escape(value), styles["BodyText"]))
        if issue.get("reproduction_steps"):
            story.append(Paragraph("<b>Reproduction steps</b>", styles["BodyText"]))
            for index, step in enumerate(issue["reproduction_steps"], start=1):
                story.append(Paragraph(f"{index}. " + _escape(str(step)), styles["BodyText"]))
        for item in issue.get("evidence", []):
            path = item.get("path")
            if not path or not evidence_store:
                continue
            try:
                image_bytes = evidence_store.read(_session_from_path(path), path.split("/")[-1])
            except Exception:
                continue
            try:
                from io import BytesIO as _BytesIO

                from PIL import Image as PILImage

                img = PILImage.open(_BytesIO(image_bytes))
                width, height = img.size
                max_width = 160 * mm
                ratio = min(1.0, max_width / width)
                story.append(Image(_BytesIO(image_bytes), width=width * ratio, height=height * ratio))
            except Exception:
                continue
        story.append(Spacer(1, 8))

    if not data["issues"]:
        story.append(p("No issues were recorded during this scan."))
    story.append(PageBreak())
    story.append(h("Coverage and limitations", 2))
    story.append(
        p(
            "This report covers only the pages and elements listed in the scan. "
            "It is not a statement that the application is free of other defects. "
            "Root causes are hypotheses unless explicitly marked as confirmed."
        )
    )

    doc.build(story)
    return buffer.getvalue()


def _session_from_path(path: str) -> str:
    parts = [p for p in path.replace("\\", "/").split("/") if p]
    for index, part in enumerate(parts):
        if part == "evidence" and index + 1 < len(parts):
            return parts[index + 1]
    return parts[-2] if len(parts) >= 2 else ""


def _escape(text: str) -> str:
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\n", "<br/>")


def _render_plain_pdf(text: str) -> bytes:
    """Minimal single-page PDF fallback used when reportlab is unavailable."""
    lines = text.splitlines()[:60]
    content = ["BT", "/F1 9 Tf", "12 TL", "40 800 Td"]
    for line in lines:
        escaped = line.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")
        content.append(f"({escaped}) Tj")
        content.append("T*")
    content.append("ET")
    stream = "\n".join(content).encode("latin-1", "replace")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources "
        b"<< /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for index, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{index} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode()
    out += b"0000000000 65535 f \n"
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    out += (f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n").encode()
    return bytes(out)


def render_zip(data: dict[str, Any], evidence_store: EvidenceStore) -> bytes:
    """Bundle the report with the evidence files it references."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as bundle:
        bundle.writestr("report.md", render_markdown(data))
        try:
            bundle.writestr("report.pdf", render_pdf(data, evidence_store))
        except Exception:
            pass
        bundle.writestr("report-data.json", json.dumps(data, indent=2, default=str))
        manifest: list[dict[str, Any]] = []
        written: set[str] = set()
        for issue in data["issues"]:
            for item in issue.get("evidence", []):
                path = item.get("path")
                if not path:
                    continue
                session_id = _session_from_path(path)
                filename = path.replace("\\", "/").split("/")[-1]
                archive_name = f"evidence/{session_id}/{filename}"
                if archive_name in written:
                    # The same screenshot can be referenced by several issues.
                    continue
                try:
                    payload = evidence_store.read(session_id, filename)
                except Exception:
                    continue
                bundle.writestr(archive_name, payload)
                written.add(archive_name)
                manifest.append(
                    {
                        "issue_id": issue["id"],
                        "kind": item["kind"],
                        "path": archive_name,
                        "original_path": path,
                    }
                )
        bundle.writestr("evidence-manifest.json", json.dumps(manifest, indent=2))
    return buffer.getvalue()
