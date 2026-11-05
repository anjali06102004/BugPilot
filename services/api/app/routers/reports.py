from __future__ import annotations

from typing import Any

from bugpilot_core.db.models import (
    Finding,
    Issue,
    IssueEvidence,
    IssueOccurrence,
    Project,
    TestSession,
)
from bugpilot_core.reporting import (
    collect_project_report,
    collect_scan_report,
    issue_dict,
    render_finding_markdown,
    render_issue_markdown,
    render_markdown,
    render_pdf,
    render_zip,
)
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, PlainTextResponse, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import get_db, get_evidence_store, not_found
from app.serializers import finding_out, issue_out

router = APIRouter(tags=["reports"])


@router.get("/reports/scan/{scan_id}.md")
async def scan_report_markdown(scan_id: str, db: AsyncSession = Depends(get_db)) -> PlainTextResponse:
    session = await db.get(TestSession, scan_id)
    if not session:
        raise not_found("Scan", scan_id)
    data = await collect_scan_report(db, session)
    return PlainTextResponse(
        render_markdown(data),
        media_type="text/markdown",
        headers={"Content-Disposition": f'attachment; filename="bugpilot-{scan_id}.md"'},
    )


@router.get("/reports/scan/{scan_id}.pdf")
async def scan_report_pdf(
    scan_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Response:
    session = await db.get(TestSession, scan_id)
    if not session:
        raise not_found("Scan", scan_id)
    data = await collect_scan_report(db, session)
    store = get_evidence_store(request)
    pdf = render_pdf(data, store)
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="bugpilot-{scan_id}.pdf"'},
    )


@router.get("/reports/scan/{scan_id}.zip")
async def scan_report_zip(
    scan_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Response:
    session = await db.get(TestSession, scan_id)
    if not session:
        raise not_found("Scan", scan_id)
    data = await collect_scan_report(db, session)
    store = get_evidence_store(request)
    bundle = render_zip(data, store)
    return Response(
        content=bundle,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="bugpilot-{scan_id}.zip"'},
    )


@router.get("/reports/project/{project_id}.md")
async def project_report_markdown(
    project_id: str,
    db: AsyncSession = Depends(get_db),
) -> PlainTextResponse:
    project = await db.get(Project, project_id)
    if not project:
        raise not_found("Project", project_id)
    data = await collect_project_report(db, project)
    return PlainTextResponse(
        render_markdown(data),
        media_type="text/markdown",
        headers={"Content-Disposition": f'attachment; filename="bugpilot-{project_id}.md"'},
    )


@router.get("/reports/project/{project_id}.pdf")
async def project_report_pdf(
    project_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Response:
    project = await db.get(Project, project_id)
    if not project:
        raise not_found("Project", project_id)
    data = await collect_project_report(db, project)
    return Response(
        content=render_pdf(data, get_evidence_store(request)),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="bugpilot-{project_id}.pdf"'},
    )


@router.get("/reports/issue/{issue_id}.md")
async def issue_markdown_export(
    issue_id: str,
    db: AsyncSession = Depends(get_db),
) -> PlainTextResponse:
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

    payload = issue_dict(issue, occurrences, evidence)
    return PlainTextResponse(
        render_issue_markdown(payload),
        media_type="text/markdown",
        headers={"Content-Disposition": f'attachment; filename="bugpilot-issue-{issue_id}.md"'},
    )


@router.get("/reports/finding/{finding_id}.md")
async def finding_export(
    finding_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> PlainTextResponse:
    finding = await db.get(Finding, finding_id)
    if not finding:
        raise not_found("Finding", finding_id)
    issue = await db.get(Issue, finding.issue_id) if finding.issue_id else None
    from app.routers.findings import evidence_url_for

    payload = finding_out(finding, evidence_url=evidence_url_for(request, finding.screenshot_path))
    issue_payload = issue_out(issue) if issue else None
    return PlainTextResponse(
        render_finding_markdown(payload, issue_payload),
        media_type="text/markdown",
        headers={"Content-Disposition": f'attachment; filename="bugpilot-finding-{finding_id}.md"'},
    )


@router.get("/reports/issue/{issue_id}.json")
async def issue_export(issue_id: str, db: AsyncSession = Depends(get_db)) -> JSONResponse:
    issue = await db.get(Issue, issue_id)
    if not issue:
        raise not_found("Issue", issue_id)
    occurrences = (
        (await db.execute(select(IssueOccurrence).where(IssueOccurrence.issue_id == issue_id)))
        .scalars()
        .all()
    )
    payload = issue_out(issue, occurrences=occurrences)
    return JSONResponse(payload)


# The plain JSON route is registered last so the `.md`, `.pdf` and `.zip`
# variants are matched before it.
@router.get("/reports/scan/{scan_id}")
async def scan_report(scan_id: str, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    session = await db.get(TestSession, scan_id)
    if not session:
        raise not_found("Scan", scan_id)
    data = await collect_scan_report(db, session)
    return {"scan_id": scan_id, "markdown": render_markdown(data), "data": data}
