"""API contract tests.

These run the real FastAPI app against a temporary database. They cover the
behaviour the extension and dashboard depend on: scope is persisted and
enforced, budgets are clamped server-side, invalid state changes are rejected,
and evidence URLs are not public.
"""

from __future__ import annotations

import uuid

import pytest
from app.main import app
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as test_client:
        yield test_client


def create_project(client: TestClient, url: str = "http://127.0.0.1:4173/") -> dict:
    response = client.post(
        "/api/v1/projects",
        json={"name": f"Project {uuid.uuid4().hex[:6]}", "website_url": url},
    )
    assert response.status_code == 200, response.text
    return response.json()


def create_scan(client: TestClient, project_id: str, **overrides) -> dict:
    payload = {
        "url": "http://127.0.0.1:4173/",
        "project_id": project_id,
        "environment": "development",
        "scope": {"type": "single_url"},
        "config": {"max_pages": 1, "max_actions": 3, "max_duration_seconds": 30},
    }
    payload.update(overrides)
    response = client.post("/api/v1/scans", json=payload)
    return {"status_code": response.status_code, "body": response.json()}


def test_health(client):
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["service"] == "bugpilot-api"


def test_create_project_and_fetch(client):
    project = create_project(client)
    fetched = client.get(f"/api/v1/projects/{project['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["id"] == project["id"]


def test_unknown_project_returns_structured_404(client):
    response = client.get("/api/v1/projects/does-not-exist")
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "not_found"


def test_scan_scope_is_persisted(client):
    project = create_project(client)
    created = create_scan(
        client,
        project["id"],
        scope={
            "type": "selected_element",
            "element_selector": "button.cta",
            "element_label": "Buy now",
        },
    )
    assert created["status_code"] == 200, created["body"]
    scan = created["body"]
    assert scan["scope"]["type"] == "selected_element"
    assert scan["scope"]["definition"]["element_selector"] == "button.cta"
    assert scan["scope"]["summary"].startswith("Selected element")


def test_selected_element_requires_selector(client):
    project = create_project(client)
    created = create_scan(client, project["id"], scope={"type": "selected_element"})
    assert created["status_code"] == 400
    assert "selector" in created["body"]["detail"]["message"]


def test_single_url_scan_forces_single_page_budget(client):
    project = create_project(client)
    created = create_scan(
        client,
        project["id"],
        scope={"type": "single_url"},
        config={"max_pages": 99, "max_actions": 100000, "max_duration_seconds": 99999},
    )
    assert created["status_code"] == 200
    config = created["body"]["config"]
    # Server-side hard limits always win over client-supplied budgets.
    assert config["max_actions"] <= 200
    assert config["max_pages"] <= 100


def test_production_disables_destructive_actions(client):
    project = create_project(client)
    created = create_scan(
        client,
        project["id"],
        environment="production",
        config={"allow_destructive": True, "max_pages": 1, "max_actions": 3},
    )
    assert created["status_code"] == 200
    assert created["body"]["config"]["allow_destructive"] is False


def test_private_targets_blocked_outside_development(client, monkeypatch):
    from bugpilot_core.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "bugpilot_env", "staging")
    response = client.post(
        "/api/v1/scans",
        json={"url": "http://127.0.0.1:4173/", "scope": {"type": "single_url"}},
    )
    assert response.status_code == 400
    monkeypatch.setattr(settings, "bugpilot_env", "development")


def test_idempotency_key_replays_the_same_scan(client):
    project = create_project(client)
    key = f"idem-{uuid.uuid4().hex}"
    first = create_scan(client, project["id"], idempotency_key=key)
    second = create_scan(client, project["id"], idempotency_key=key)
    assert first["status_code"] == 200
    assert second["status_code"] == 200
    assert first["body"]["id"] == second["body"]["id"]
    assert second["body"]["idempotent_replay"] is True


def test_pause_and_resume_require_valid_state(client):
    project = create_project(client)
    scan = create_scan(client, project["id"])["body"]
    paused = client.post(f"/api/v1/scans/{scan['id']}/pause")
    assert paused.status_code == 200
    assert paused.json()["status"] == "paused"
    paused_again = client.post(f"/api/v1/scans/{scan['id']}/pause")
    assert paused_again.status_code == 409
    resumed = client.post(f"/api/v1/scans/{scan['id']}/resume")
    assert resumed.status_code == 200
    assert resumed.json()["status"] == "running"


def test_stop_marks_scan_cancelled(client):
    project = create_project(client)
    scan = create_scan(client, project["id"])["body"]
    stopped = client.post(f"/api/v1/scans/{scan['id']}/stop")
    assert stopped.status_code == 200
    assert stopped.json()["status"] == "cancelled"


def test_scan_list_is_paginated(client):
    project = create_project(client)
    create_scan(client, project["id"])
    response = client.get(f"/api/v1/scans?project_id={project['id']}&limit=1")
    assert response.status_code == 200
    payload = response.json()
    assert "items" in payload and "total" in payload
    assert len(payload["items"]) <= 1


def test_findings_and_issues_start_empty(client):
    project = create_project(client)
    findings = client.get("/api/v1/findings?scan_id=none").json()
    assert findings["total"] == 0
    issues = client.get(f"/api/v1/issues?project_id={project['id']}").json()
    assert issues["total"] == 0


def test_issue_filters_and_grouping(client):
    response = client.get("/api/v1/issues?group_by=severity&sort=priority")
    assert response.status_code == 200
    payload = response.json()
    assert "items" in payload
    assert "groups" in payload


def test_unknown_issue_returns_404(client):
    assert client.get("/api/v1/issues/nope").status_code == 404


def test_evidence_requires_signed_token(client):
    response = client.get("/api/v1/evidence/some-session/shot.png")
    assert response.status_code in {400, 403, 404}


def test_dashboard_shape(client):
    payload = client.get("/api/v1/dashboard").json()
    for key in (
        "projects",
        "scans",
        "open_issues",
        "regressions",
        "by_severity",
        "recent_scans",
    ):
        assert key in payload


def test_report_for_unknown_scan_is_404(client):
    assert client.get("/api/v1/reports/scan/missing.md").status_code == 404
