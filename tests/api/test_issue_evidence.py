"""Registry evidence URLs.

The issue workspace must show the screenshots the agent captured, not just an
evidence count. Evidence URLs are signed, like finding evidence.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
from app.main import app
from bugpilot_core.db import SessionLocal, init_db
from bugpilot_core.db.models import Issue, IssueEvidence, Project
from fastapi.testclient import TestClient


async def seed_issue() -> str:
    await init_db()
    async with SessionLocal() as db:
        project = Project(
            id=str(uuid.uuid4()),
            name="Registry evidence",
            website_url="https://shop.example.com/",
            environment="staging",
        )
        issue = Issue(
            id=str(uuid.uuid4()),
            issue_key=f"key-{uuid.uuid4().hex}",
            project_id=project.id,
            title="Broken image",
            summary="The hero image does not load.",
            description="naturalWidth=0",
            category="broken_image",
            severity="medium",
            priority="P2",
            confidence_label="confirmed",
            confidence=0.97,
            status="new",
            source="broken_images_detector",
            url="https://shop.example.com/cart",
            route="/cart",
        )
        db.add(project)
        db.add(issue)
        db.add(
            IssueEvidence(
                id=str(uuid.uuid4()),
                issue_id=issue.id,
                session_id="session-xyz",
                kind="screenshot",
                path="data/evidence/session-xyz/shot.png",
                content={"value": None},
                redacted=True,
            )
        )
        await db.commit()
        return issue.id


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as test_client:
        yield test_client


def test_issue_evidence_has_signed_urls(client):
    issue_id = asyncio.run(seed_issue())
    payload = client.get(f"/api/v1/issues/{issue_id}").json()
    assert payload["evidence"], "issue detail must include evidence records"
    screenshot = next(e for e in payload["evidence"] if e["kind"] == "screenshot")
    assert screenshot["url"] is not None
    assert screenshot["url"].startswith("/api/v1/evidence/session-xyz/shot.png")
    assert "token=" in screenshot["url"]
    assert screenshot["redacted"] is True
