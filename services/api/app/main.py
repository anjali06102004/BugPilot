import asyncio
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import func, select

from bugpilot_core.config import get_settings
from bugpilot_core.db import SessionLocal, init_db
from bugpilot_core.db.models import Finding, FindingEvidence, Project, TestSession
from bugpilot_core.events import EventBus
from bugpilot_core.models import CreateScanRequest, ScanConfig, ScanStatus
from bugpilot_core.security import TargetValidationError, validate_scan_target

settings = get_settings()
bus = EventBus(settings)
app = FastAPI(title="BugPilot AI", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.web_origin, "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class FindingUpdate(BaseModel):
    status: str | None = None
    severity: str | None = None


@app.on_event("startup")
async def startup() -> None:
    settings.evidence_dir.mkdir(parents=True, exist_ok=True)
    await init_db()
    await bus.connect()


@app.on_event("shutdown")
async def shutdown() -> None:
    await bus.close()


@app.get("/health")
async def health() -> dict:
    return {"ok": True, "service": "bugpilot-api", "phase": 1}


@app.post("/projects")
async def create_project(body: CreateScanRequest) -> dict:
    url = validate_scan_target(str(body.url), settings)
    async with SessionLocal() as db:
        project = Project(
            id=str(uuid4()),
            name=body.project_name,
            website_url=url,
            environment=body.environment,
            description=body.description,
        )
        db.add(project)
        await db.commit()
        return {"id": project.id, "name": project.name, "website_url": project.website_url}


@app.get("/projects")
async def list_projects() -> list[dict]:
    async with SessionLocal() as db:
        rows = (await db.execute(select(Project).order_by(Project.created_at.desc()))).scalars().all()
        return [
            {
                "id": p.id,
                "name": p.name,
                "website_url": p.website_url,
                "environment": p.environment,
                "description": p.description,
            }
            for p in rows
        ]


@app.post("/scans")
async def create_scan(body: CreateScanRequest) -> dict:
    try:
        url = validate_scan_target(str(body.url), settings)
    except TargetValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    config = body.config
    if body.environment == "production":
        config = config.model_copy(update={"allow_destructive": False, "environment": "production"})
    config = config.model_copy(
        update={
            "max_pages": min(config.max_pages, settings.max_pages_hard_limit),
            "max_duration_seconds": min(config.max_duration_seconds, settings.max_duration_seconds_hard_limit),
            "environment": body.environment,
        }
    )

    async with SessionLocal() as db:
        project = Project(
            id=str(uuid4()),
            name=body.project_name,
            website_url=url,
            environment=body.environment,
            description=body.description,
        )
        session = TestSession(
            id=str(uuid4()),
            project_id=project.id,
            start_url=url,
            status=ScanStatus.QUEUED.value,
            config_json=config.model_dump(),
        )
        db.add(project)
        db.add(session)
        await db.commit()
        queued = await bus.enqueue_scan(session.id)
        return {
            "id": session.id,
            "project_id": project.id,
            "status": session.status,
            "queued_on_redis": queued,
            "start_url": url,
        }


@app.get("/scans/{scan_id}")
async def get_scan(scan_id: str) -> dict:
    async with SessionLocal() as db:
        session = await db.get(TestSession, scan_id)
        if not session:
            raise HTTPException(status_code=404, detail="Scan not found")
        findings = (
            await db.execute(select(Finding).where(Finding.session_id == scan_id))
        ).scalars().all()
        events = [e.model_dump(mode="json") for e in await bus.history(scan_id)]
        return {
            "id": session.id,
            "project_id": session.project_id,
            "start_url": session.start_url,
            "status": session.status,
            "error_message": session.error_message,
            "pages_tested": session.pages_tested,
            "actions_taken": session.actions_taken,
            "config": session.config_json,
            "findings": [_finding_out(f) for f in findings],
            "events": events,
        }


@app.post("/scans/{scan_id}/stop")
async def stop_scan(scan_id: str) -> dict:
    async with SessionLocal() as db:
        session = await db.get(TestSession, scan_id)
        if not session:
            raise HTTPException(status_code=404, detail="Scan not found")
        session.status = ScanStatus.STOPPED.value
        session.completed_at = datetime.now(timezone.utc)
        await db.commit()
        return {"id": session.id, "status": session.status}


@app.get("/scans/{scan_id}/findings")
async def scan_findings(scan_id: str) -> list[dict]:
    async with SessionLocal() as db:
        rows = (await db.execute(select(Finding).where(Finding.session_id == scan_id))).scalars().all()
        return [_finding_out(f) for f in rows]


@app.get("/findings/{finding_id}")
async def get_finding(finding_id: str) -> dict:
    async with SessionLocal() as db:
        finding = await db.get(Finding, finding_id)
        if not finding:
            raise HTTPException(status_code=404, detail="Finding not found")
        evidence = (
            await db.execute(select(FindingEvidence).where(FindingEvidence.finding_id == finding_id))
        ).scalars().all()
        payload = _finding_out(finding)
        payload["evidence"] = [
            {"id": e.id, "kind": e.kind, "path": e.path, "content": e.content} for e in evidence
        ]
        payload["ai_disclaimer"] = "AI-generated suggestion — verify before applying." if finding.suggested_fix else None
        return payload


@app.patch("/findings/{finding_id}")
async def update_finding(finding_id: str, body: FindingUpdate) -> dict:
    async with SessionLocal() as db:
        finding = await db.get(Finding, finding_id)
        if not finding:
            raise HTTPException(status_code=404, detail="Finding not found")
        if body.status:
            finding.status = body.status
        if body.severity:
            finding.severity = body.severity
        await db.commit()
        return _finding_out(finding)


@app.get("/reports/{scan_id}")
async def get_report(scan_id: str) -> dict:
    async with SessionLocal() as db:
        session = await db.get(TestSession, scan_id)
        if not session:
            raise HTTPException(status_code=404, detail="Scan not found")
        findings = (
            await db.execute(select(Finding).where(Finding.session_id == scan_id))
        ).scalars().all()
        md = [f"# BugPilot report", f"", f"Target: {session.start_url}", f"Status: {session.status}", ""]
        for f in findings:
            md += [
                f"## {f.title}",
                f"Severity: {f.severity}",
                f"Confidence: {int(f.confidence * 100)}%",
                f"Status: {f.status}",
                f"URL: {f.url}",
                "",
                f.description,
                "",
                f"Expected: {f.expected or ''}",
                f"Actual: {f.actual or ''}",
                "",
            ]
        return {"scan_id": scan_id, "markdown": "\n".join(md), "json": [_finding_out(f) for f in findings]}


@app.get("/dashboard")
async def dashboard() -> dict:
    async with SessionLocal() as db:
        projects = (await db.execute(select(func.count(Project.id)))).scalar_one()
        scans = (await db.execute(select(func.count(TestSession.id)))).scalar_one()
        active = (
            await db.execute(select(func.count(TestSession.id)).where(TestSession.status.in_(["queued", "running"])))
        ).scalar_one()
        bugs = (await db.execute(select(func.count(Finding.id)))).scalar_one()
        verified = (
            await db.execute(select(func.count(Finding.id)).where(Finding.status == "verified"))
        ).scalar_one()
        rejected = (
            await db.execute(
                select(func.count(Finding.id)).where(Finding.status.in_(["rejected", "not_a_bug"]))
            )
        ).scalar_one()
        pages = (await db.execute(select(func.coalesce(func.sum(TestSession.pages_tested), 0)))).scalar_one()
        recent = (
            await db.execute(select(TestSession).order_by(TestSession.created_at.desc()).limit(8))
        ).scalars().all()
        false_positive_rate = (rejected / bugs) if bugs else 0
        return {
            "projects": projects,
            "scans": scans,
            "active_scans": active,
            "total_bugs": bugs,
            "verified_bugs": verified,
            "false_positive_rate": false_positive_rate,
            "pages_tested": int(pages or 0),
            "recent_activity": [
                {"id": s.id, "url": s.start_url, "status": s.status, "pages_tested": s.pages_tested}
                for s in recent
            ],
        }


@app.get("/evidence/{session_id}/{filename}")
async def get_evidence_file(session_id: str, filename: str):
    path = settings.evidence_dir / session_id / filename
    if not path.exists() or path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
        raise HTTPException(status_code=404, detail="Evidence not found")
    return FileResponse(path)


@app.websocket("/scans/{scan_id}/events")
async def scan_events(websocket: WebSocket, scan_id: str) -> None:
    await websocket.accept()
    queue: list[dict] = []

    async def handler(event):
        queue.append(event.model_dump(mode="json"))

    bus.subscribe_local(scan_id, handler)
    try:
        for event in await bus.history(scan_id):
            await websocket.send_json(event.model_dump(mode="json"))
        while True:
            if queue:
                await websocket.send_json(queue.pop(0))
            else:
                    try:
                    await asyncio.wait_for(websocket.receive_text(), timeout=0.4)
                except TimeoutError:
                    continue
    except WebSocketDisconnect:
        return


def _finding_out(finding: Finding) -> dict:
    screenshot = None
    return {
        "id": finding.id,
        "session_id": finding.session_id,
        "category": finding.category,
        "title": finding.title,
        "description": finding.description,
        "severity": finding.severity,
        "confidence": finding.confidence,
        "confidence_label": finding.confidence_label,
        "status": finding.status,
        "source": finding.source,
        "url": finding.url,
        "selector": finding.selector,
        "expected": finding.expected,
        "actual": finding.actual,
        "steps": finding.steps_json,
        "suggested_fix": finding.suggested_fix,
        "root_cause": finding.root_cause,
        "reproduced_count": finding.reproduced_count,
        "verification_attempts": finding.verification_attempts,
        "created_at": finding.created_at.isoformat() if finding.created_at else None,
        "screenshot": screenshot,
    }


def run() -> None:
    import uvicorn

    uvicorn.run("app.main:app", host=settings.api_host, port=settings.api_port, reload=True)
