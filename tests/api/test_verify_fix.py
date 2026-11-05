"""Phase 6 contracts: post-fix verification through the API.

The browser is replaced with a stub here; `scripts/e2e_verification.py` runs
the real replay against the fixture.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
from app.main import app
from bugpilot_core.db import SessionLocal, init_db
from bugpilot_core.db.models import Issue, Project
from bugpilot_core.verification import VerificationOutcome
from fastapi.testclient import TestClient


async def seed_issue(status: str = "fixed") -> str:
    await init_db()
    async with SessionLocal() as db:
        project = Project(
            id=str(uuid.uuid4()),
            name="Verification project",
            website_url="https://shop.example.com/",
            environment="staging",
        )
        issue = Issue(
            id=str(uuid.uuid4()),
            issue_key=f"verify-{uuid.uuid4().hex}",
            project_id=project.id,
            title="Horizontal overflow on page",
            summary="Cart scrolls sideways on mobile.",
            description="scrollWidth 1400 > clientWidth 390",
            category="overflow",
            severity="medium",
            priority="P2",
            confidence_label="confirmed",
            confidence=0.95,
            status=status,
            source="overflow_detector",
            url="https://shop.example.com/cart",
            route="/cart",
            fingerprint="fp-verify",
            error_signature="h-overflow:390",
            extra={
                "reproduction": {
                    "url": "https://shop.example.com/cart",
                    "selector": None,
                    "error_signature": "h-overflow:390",
                    "actions": [{"type": "scroll", "selector": "body"}],
                }
            },
        )
        db.add(project)
        db.add(issue)
        await db.commit()
        return issue.id


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as test_client:
        yield test_client


def stub(monkeypatch, verdict: str, notes: str = "stub"):
    async def fake(issue, *, settings, author=None):
        return VerificationOutcome(
            verdict=verdict,
            method="replay",
            notes=notes,
            actions_replayed=1,
            actions_failed=0,
        )

    monkeypatch.setattr("app.routers.issues.verify_issue", fake)


def test_verify_fixed_marks_issue_verified(client, monkeypatch):
    issue_id = asyncio.run(seed_issue("fixed"))
    stub(monkeypatch, "fixed", "Detector signal is gone after replay.")
    response = client.post(f"/api/v1/issues/{issue_id}/verify-fix", json={"author": "qa"})
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["verdict"] == "fixed"
    assert payload["issue"]["status"] == "verified"
    assert payload["issue"]["last_verified_at"] is not None

    history = client.get(f"/api/v1/issues/{issue_id}/verifications").json()
    assert history["total"] == 1
    assert history["items"][0]["verdict"] == "fixed"


def test_verify_still_failing_reopens_and_flags_regression(client, monkeypatch):
    issue_id = asyncio.run(seed_issue("fixed"))
    stub(monkeypatch, "still_failing", "Same detector signal is still present.")
    payload = client.post(f"/api/v1/issues/{issue_id}/verify-fix", json={}).json()
    assert payload["verdict"] == "still_failing"
    assert payload["issue"]["status"] == "reopened"
    assert payload["issue"]["is_regression"] is True
    assert payload["issue"]["reopened_count"] >= 1


def test_inconclusive_never_claims_a_fix(client, monkeypatch):
    issue_id = asyncio.run(seed_issue("in_progress"))
    stub(monkeypatch, "inconclusive", "The page could not be inspected.")
    payload = client.post(f"/api/v1/issues/{issue_id}/verify-fix", json={}).json()
    assert payload["verdict"] == "inconclusive"
    assert payload["issue"]["status"] == "needs_review"
    assert payload["issue"]["last_verified_at"] is None


def test_verification_is_audited_in_activity(client, monkeypatch):
    issue_id = asyncio.run(seed_issue("confirmed"))
    stub(monkeypatch, "still_failing")
    client.post(
        f"/api/v1/issues/{issue_id}/verify-fix", json={"author": "qa", "body": "checked after deploy"}
    )
    detail = client.get(f"/api/v1/issues/{issue_id}").json()
    kinds = [event["kind"] for event in detail["events"]]
    assert "verification" in kinds
    assert detail["verifications"]


def test_verify_unknown_issue_is_404(client):
    assert client.post("/api/v1/issues/does-not-exist/verify-fix", json={}).status_code == 404
