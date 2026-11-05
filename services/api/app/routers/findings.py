from __future__ import annotations

import os
from typing import Any

from bugpilot_core.config import Settings
from bugpilot_core.db.models import Finding, FindingEvidence
from bugpilot_core.evidence import EvidenceError
from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import (
    bad_request,
    get_db,
    get_evidence_store,
    get_settings_dep,
    not_found,
    pagination,
)
from app.serializers import finding_out

router = APIRouter(tags=["findings"])


class UpdateFindingRequest(BaseModel):
    status: str | None = None
    severity: str | None = None
    priority: str | None = None
    suggested_fix: str | None = None
    root_cause: str | None = None
    root_cause_status: str | None = None
    business_impact: str | None = None
    assigned_to: str | None = None


def evidence_url_for(request: Request, path: str | None) -> str | None:
    """Build a signed, versioned evidence URL for a stored artifact.

    Evidence access is authorized: the API returns `/api/v1/evidence/...` with
    an HMAC token, never a guessable static path.
    """
    if not path:
        return None
    normalized = path.replace("\\", "/")
    parts = [p for p in normalized.split("/") if p]
    if len(parts) < 2:
        return None
    session_id, filename = parts[-2], parts[-1]
    store = get_evidence_store(request)
    token = store.sign(session_id, filename)
    return f"/api/v1/evidence/{session_id}/{filename}?token={token}"


@router.get("/findings")
async def list_findings(
    scan_id: str | None = None,
    issue_id: str | None = None,
    category: str | None = None,
    severity: str | None = None,
    page=Depends(pagination),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    stmt = select(Finding)
    count_stmt = select(func.count(Finding.id))
    if scan_id:
        stmt = stmt.where(Finding.session_id == scan_id)
        count_stmt = count_stmt.where(Finding.session_id == scan_id)
    if issue_id:
        stmt = stmt.where(Finding.issue_id == issue_id)
        count_stmt = count_stmt.where(Finding.issue_id == issue_id)
    if category:
        stmt = stmt.where(Finding.category == category)
        count_stmt = count_stmt.where(Finding.category == category)
    if severity:
        stmt = stmt.where(Finding.severity == severity)
        count_stmt = count_stmt.where(Finding.severity == severity)
    total = (await db.execute(count_stmt)).scalar_one()
    rows = (
        (await db.execute(stmt.order_by(Finding.created_at.desc()).limit(page.limit).offset(page.offset)))
        .scalars()
        .all()
    )
    return {"items": [finding_out(f) for f in rows], "total": total, **page.as_dict()}


@router.get("/findings/{finding_id}")
async def get_finding(
    finding_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    finding = await db.get(Finding, finding_id)
    if not finding:
        raise not_found("Finding", finding_id)
    evidence = (
        (await db.execute(select(FindingEvidence).where(FindingEvidence.finding_id == finding_id)))
        .scalars()
        .all()
    )
    payload = finding_out(finding, evidence_url=evidence_url_for(request, finding.screenshot_path))
    payload["evidence"] = [
        {
            "id": e.id,
            "kind": e.kind,
            "path": e.path,
            "url": evidence_url_for(request, e.path),
            "content": e.content,
        }
        for e in evidence
    ]
    payload["ai_disclaimer"] = (
        "AI-generated suggestion — verify before applying." if finding.suggested_fix else None
    )
    return payload


@router.patch("/findings/{finding_id}")
async def update_finding(
    finding_id: str,
    body: UpdateFindingRequest,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    finding = await db.get(Finding, finding_id)
    if not finding:
        raise not_found("Finding", finding_id)
    if body.status:
        finding.status = body.status
    if body.severity:
        finding.severity = body.severity
    if body.priority:
        finding.priority = body.priority
    if body.suggested_fix is not None:
        finding.suggested_fix = body.suggested_fix
    if body.root_cause is not None:
        finding.root_cause = body.root_cause
    if body.root_cause_status is not None:
        finding.root_cause_status = body.root_cause_status
    extra = dict(finding.extra or {})
    if body.business_impact is not None:
        extra["business_impact"] = body.business_impact
    if body.assigned_to is not None:
        extra["assigned_to"] = body.assigned_to
    finding.extra = extra
    await db.commit()
    return finding_out(finding)


@router.get("/evidence/{session_id}/{filename}")
async def get_evidence_file(
    session_id: str,
    filename: str,
    request: Request,
    token: str | None = None,
    settings: Settings = Depends(get_settings_dep),
):
    store = get_evidence_store(request)
    if not settings.evidence_public:
        if not token:
            raise bad_request("A signed evidence token is required for this file.")
        verified = store.verify(token)
        if not verified or verified[0] != session_id or verified[1] != filename:
            from fastapi import HTTPException

            raise HTTPException(status_code=403, detail="Invalid or expired evidence token.")
    suffix = os.path.splitext(filename)[1].lower()
    if suffix not in {".png", ".jpg", ".jpeg", ".webp"}:
        raise not_found("Evidence file", filename)
    try:
        path = store.path_for(session_id, filename)
    except EvidenceError as exc:
        raise bad_request(str(exc)) from exc
    if not path.exists():
        raise not_found("Evidence file", filename)
    return FileResponse(path)
