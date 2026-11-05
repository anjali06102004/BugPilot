"""Evidence URL contracts.

Phase 1 requires finding responses to carry usable evidence URLs. These are
authorized (signed) URLs, not guessable static paths.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
from app.main import app
from bugpilot_core.db import SessionLocal, init_db
from bugpilot_core.db.models import (
    Finding,
    FindingEvidence,
    Project,
    TestSession,
)
from fastapi.testclient import TestClient


async def seed_finding(screenshot_path: str) -> tuple[str, str]:
    await init_db()
    async with SessionLocal() as db:
        project = Project(
            id=str(uuid.uuid4()),
            name="Evidence project",
            website_url="https://shop.example.com/",
            environment="staging",
        )
        session = TestSession(
            id=str(uuid.uuid4()),
            project_id=project.id,
            start_url="https://shop.example.com/cart",
            status="completed",
            scope_type="single_url",
            scope_json={"type": "single_url", "start_url": "https://shop.example.com/cart"},
            config_json={},
        )
        finding = Finding(
            id=str(uuid.uuid4()),
            session_id=session.id,
            category="overflow",
            title="Horizontal overflow on page",
            description="wide",
            severity="medium",
            priority="P2",
            confidence=0.9,
            confidence_label="confirmed",
            status="verified",
            source="overflow_detector",
            url="https://shop.example.com/cart",
            screenshot_path=screenshot_path,
            extra={"viewport": "mobile-390"},
        )
        db.add(project)
        db.add(session)
        db.add(finding)
        db.add(
            FindingEvidence(
                id=str(uuid.uuid4()),
                finding_id=finding.id,
                kind="screenshot",
                path=screenshot_path,
                content={"value": None},
            )
        )
        await db.commit()
        return session.id, finding.id


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as test_client:
        yield test_client


def test_scan_findings_expose_signed_evidence_urls(client):
    screenshot = "data/evidence/session-abc/shot.png"
    scan_id, finding_id = asyncio.run(seed_finding(screenshot))

    scan = client.get(f"/api/v1/scans/{scan_id}").json()
    finding = next(f for f in scan["findings"] if f["id"] == finding_id)
    assert finding["screenshot"], "scan findings must include an evidence URL"
    assert finding["screenshot"].startswith("/api/v1/evidence/session-abc/shot.png")
    assert "token=" in finding["screenshot"]

    detail = client.get(f"/api/v1/findings/{finding_id}").json()
    assert detail["screenshot"].startswith("/api/v1/evidence/session-abc/shot.png")
    assert detail["evidence"], "finding detail must include evidence records"
    screenshot_evidence = [e for e in detail["evidence"] if e["kind"] == "screenshot"]
    assert screenshot_evidence and screenshot_evidence[0]["url"]


def test_evidence_token_is_required(client):
    response = client.get("/api/v1/evidence/session-abc/shot.png")
    assert response.status_code == 400
    assert "signed evidence token" in response.json()["detail"]["message"]


def test_evidence_url_is_not_guessable_without_token(client):
    forged = client.get("/api/v1/evidence/session-abc/shot.png?token=not-a-real-token")
    assert forged.status_code == 403
