from __future__ import annotations

from typing import Any

from bugpilot_core.config import Settings
from bugpilot_core.db.models import Issue, Project, TestSession
from bugpilot_core.security import TargetValidationError, validate_scan_target
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import bad_request, get_db, get_settings_dep, not_found
from app.serializers import project_out

router = APIRouter(tags=["projects"])


class CreateProjectRequest(BaseModel):
    name: str = "Local project"
    website_url: str
    environment: str = "staging"
    description: str = ""
    critical_routes: list[str] = []


class UpdateProjectRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    critical_routes: list[str] | None = None
    evidence_retention_days: int | None = None


@router.post("/projects")
async def create_project(
    body: CreateProjectRequest,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings_dep),
) -> dict[str, Any]:
    try:
        url = validate_scan_target(body.website_url, settings)
    except TargetValidationError as exc:
        raise bad_request(str(exc)) from exc
    import uuid

    project = Project(
        id=str(uuid.uuid4()),
        name=body.name,
        website_url=url,
        environment=body.environment,
        description=body.description,
        critical_routes=body.critical_routes,
    )
    db.add(project)
    await db.commit()
    return project_out(project)


@router.get("/projects")
async def list_projects(db: AsyncSession = Depends(get_db)) -> list[dict[str, Any]]:
    rows = (await db.execute(select(Project).order_by(Project.created_at.desc()))).scalars().all()
    return [project_out(p) for p in rows]


@router.get("/projects/{project_id}")
async def get_project(project_id: str, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    project = await db.get(Project, project_id)
    if not project:
        raise not_found("Project", project_id)
    open_issues = (
        await db.execute(
            select(func.count(Issue.id)).where(
                Issue.project_id == project_id,
                Issue.status.notin_(["closed", "false_positive"]),
            )
        )
    ).scalar_one()
    scans = (
        await db.execute(select(func.count(TestSession.id)).where(TestSession.project_id == project_id))
    ).scalar_one()
    payload = project_out(project)
    payload["open_issues"] = open_issues
    payload["scans"] = scans
    return payload


@router.get("/dashboard")
async def dashboard(db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    """Aggregated health view for the overview screen."""
    projects = (await db.execute(select(func.count(Project.id)))).scalar_one()
    scans = (await db.execute(select(func.count(TestSession.id)))).scalar_one()
    active = (
        await db.execute(
            select(func.count(TestSession.id)).where(TestSession.status.in_(["queued", "running", "paused"]))
        )
    ).scalar_one()
    issues = (await db.execute(select(Issue))).scalars().all()
    open_issues = [i for i in issues if i.status not in {"closed", "false_positive"}]
    by_severity: dict[str, int] = {}
    by_priority: dict[str, int] = {}
    for issue in issues:
        by_severity[issue.severity] = by_severity.get(issue.severity, 0) + 1
        by_priority[issue.priority] = by_priority.get(issue.priority, 0) + 1
    rejected = sum(1 for i in issues if i.status == "false_positive")
    pages = (await db.execute(select(func.coalesce(func.sum(TestSession.pages_tested), 0)))).scalar_one()
    recent = (
        (await db.execute(select(TestSession).order_by(TestSession.created_at.desc()).limit(8)))
        .scalars()
        .all()
    )
    return {
        "projects": projects,
        "scans": scans,
        "active_scans": active,
        "total_issues": len(issues),
        "open_issues": len(open_issues),
        "regressions": sum(1 for i in issues if i.is_regression),
        "verified_issues": sum(1 for i in issues if i.status == "verified"),
        "false_positive_rate": (rejected / len(issues)) if issues else 0,
        "pages_tested": int(pages or 0),
        "by_severity": by_severity,
        "by_priority": by_priority,
        "recent_scans": [
            {
                "id": s.id,
                "url": s.start_url,
                "status": s.status,
                "pages_tested": s.pages_tested,
                "created_at": s.created_at.isoformat() if s.created_at else None,
            }
            for s in recent
        ],
    }


@router.patch("/projects/{project_id}")
async def update_project(
    project_id: str,
    body: UpdateProjectRequest,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    project = await db.get(Project, project_id)
    if not project:
        raise not_found("Project", project_id)
    if body.name is not None:
        project.name = body.name
    if body.description is not None:
        project.description = body.description
    if body.critical_routes is not None:
        project.critical_routes = body.critical_routes
    if body.evidence_retention_days is not None:
        if body.evidence_retention_days < 0:
            raise bad_request("evidence_retention_days cannot be negative.")
        project.evidence_retention_days = body.evidence_retention_days
    await db.commit()
    return project_out(project)
