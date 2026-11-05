"""Project-scoped authorization.

A key with scope `project:<id>` may only touch that project. The middleware
resolves the project from the path (project/scan/issue/finding/report ids) and
rejects cross-project access before the route runs. Routes that take a project
id in the body (scan creation, bulk triage, merge) call the same helper
explicitly.
"""

from __future__ import annotations

from bugpilot_core.db.models import Finding, Issue, TestSession
from fastapi import HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import Principal, principal_of, require_project


def forbidden(message: str) -> HTTPException:
    return HTTPException(
        status_code=403,
        detail={"code": "forbidden", "message": message, "details": None},
    )


async def project_of_scan(db: AsyncSession, scan_id: str) -> str | None:
    row = (
        await db.execute(select(TestSession.project_id).where(TestSession.id == scan_id))
    ).scalar_one_or_none()
    return row


async def project_of_issue(db: AsyncSession, issue_id: str) -> str | None:
    row = (await db.execute(select(Issue.project_id).where(Issue.id == issue_id))).scalar_one_or_none()
    return row


async def project_of_finding(db: AsyncSession, finding_id: str) -> str | None:
    finding = (await db.execute(select(Finding).where(Finding.id == finding_id))).scalar_one_or_none()
    if finding is None:
        return None
    return await project_of_scan(db, finding.session_id)


def _segments(path: str) -> list[str]:
    return [part for part in path.split("/") if part]


async def enforce_path_scope(request: Request, db: AsyncSession) -> None:
    """Reject a project-scoped key touching another project, using the path."""
    principal = principal_of(request)
    if principal is None or principal.is_admin:
        return
    parts = _segments(request.url.path)
    # Expect /api/v1/<resource>/...
    if len(parts) < 3 or parts[0] != "api":
        return
    resource = parts[2]
    rest = parts[3:]

    project_id: str | None = None
    if resource == "projects" and rest:
        project_id = rest[0]
    elif resource == "reports" and len(rest) >= 2:
        kind, identifier = rest[0], rest[1].split(".")[0]
        if kind == "project":
            project_id = identifier
        elif kind == "scan":
            project_id = await project_of_scan(db, identifier)
        elif kind == "issue":
            project_id = await project_of_issue(db, identifier)
        elif kind == "finding":
            project_id = await project_of_finding(db, identifier)
    elif resource == "scans":
        if rest:
            project_id = await project_of_scan(db, rest[0])
        else:
            project_id = request.query_params.get("project_id")
            if not project_id:
                raise forbidden("This API key is scoped to a project; pass project_id when listing scans.")
    elif resource == "issues":
        if rest and rest[0] not in {"stats", "trends", "bulk"}:
            project_id = await project_of_issue(db, rest[0])
        else:
            project_id = request.query_params.get("project_id")
            if not project_id and rest and rest[0] in {"stats", "trends"}:
                raise forbidden(
                    "This API key is scoped to a project; pass project_id when reading registry stats."
                )
    elif resource == "findings":
        if rest:
            project_id = await project_of_finding(db, rest[0])
    elif resource == "dashboard":
        raise forbidden("The dashboard aggregate requires an admin key.")
    elif resource == "metrics":
        raise forbidden("Metrics require an admin key.")

    if project_id:
        try:
            require_project(principal, project_id)
        except Exception as exc:  # AuthError
            raise forbidden(getattr(exc, "message", "Not authorized for that project.")) from exc


def assert_principal_project(principal: Principal | None, project_id: str | None) -> None:
    if principal is None:
        return
    try:
        require_project(principal, project_id)
    except Exception as exc:
        raise forbidden(getattr(exc, "message", "Not authorized for that project.")) from exc
