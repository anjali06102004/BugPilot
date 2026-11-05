"""Phase 7 contracts: access control and rate limiting."""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from app.main import app
from bugpilot_core.config import get_settings

ADMIN = "test-admin-key"
PROJECT_KEY = "test-project-key"


@pytest.fixture()
def settings():
    settings = get_settings()
    original = {
        "auth_required": settings.auth_required,
        "api_keys": settings.api_keys,
        "rate_limit_requests_per_minute": settings.rate_limit_requests_per_minute,
        "rate_limit_expensive_per_minute": settings.rate_limit_expensive_per_minute,
    }
    yield settings
    for key, value in original.items():
        setattr(settings, key, value)


@pytest.fixture()
def client(settings):
    settings.auth_required = True
    settings.api_keys = f"{ADMIN}:admin,{PROJECT_KEY}:project:pending"
    with TestClient(app) as test_client:
        yield test_client
    # reset the limiter between tests that share the app instance
    from app.auth import RateLimiter

    app.state.rate_limiter = RateLimiter()


def admin_headers() -> dict[str, str]:
    return {"X-API-Key": ADMIN}


def project_headers() -> dict[str, str]:
    return {"X-API-Key": PROJECT_KEY}


def test_health_stays_public(settings):
    settings.auth_required = True
    settings.api_keys = f"{ADMIN}:admin"
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/api/v1/health").status_code == 200


def test_missing_and_wrong_keys_are_rejected(client):
    response = client.get("/api/v1/projects")
    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "unauthorized"

    wrong = client.get("/api/v1/projects", headers={"X-API-Key": "nope"})
    assert wrong.status_code == 401


def test_admin_key_works(client):
    response = client.get("/api/v1/projects", headers=admin_headers())
    assert response.status_code == 200


def test_project_key_is_limited_to_its_project(client, settings):
    # Resolve the project id this key is scoped to by creating it as admin.
    created = client.post(
        "/api/v1/projects",
        headers=admin_headers(),
        json={"name": "Scoped", "website_url": "https://shop.example.com/"},
    ).json()
    other = client.post(
        "/api/v1/projects",
        headers=admin_headers(),
        json={"name": "Other", "website_url": "https://other.example.com/"},
    ).json()

    settings.api_keys = f"{ADMIN}:admin,{PROJECT_KEY}:project:{created['id']}"

    allowed = client.get(f"/api/v1/projects/{created['id']}", headers=project_headers())
    assert allowed.status_code == 200

    denied = client.get(f"/api/v1/projects/{other['id']}", headers=project_headers())
    assert denied.status_code == 403
    assert denied.json()["detail"]["code"] == "forbidden"

    listed = client.get("/api/v1/scans", headers=project_headers())
    assert listed.status_code == 403


def test_project_key_cannot_create_scan_for_another_project(client, settings):
    created = client.post(
        "/api/v1/projects",
        headers=admin_headers(),
        json={"name": "Scoped", "website_url": "https://shop.example.com/"},
    ).json()
    settings.api_keys = f"{ADMIN}:admin,{PROJECT_KEY}:project:{created['id']}"

    without_project = client.post(
        "/api/v1/scans",
        headers=project_headers(),
        json={"url": "https://shop.example.com/", "scope": {"type": "single_url"}},
    )
    assert without_project.status_code == 403

    other_project = client.post(
        "/api/v1/scans",
        headers=project_headers(),
        json={
            "url": "https://shop.example.com/",
            "project_id": str(uuid.uuid4()),
            "scope": {"type": "single_url"},
        },
    )
    assert other_project.status_code in {403, 404}


def test_dashboard_requires_admin(client):
    response = client.get("/api/v1/dashboard", headers=project_headers())
    assert response.status_code == 403
    assert client.get("/api/v1/dashboard", headers=admin_headers()).status_code == 200


def test_rate_limit_returns_429_with_retry_after(client, settings):
    settings.rate_limit_requests_per_minute = 2
    first = client.get("/api/v1/projects", headers=admin_headers())
    second = client.get("/api/v1/projects", headers=admin_headers())
    third = client.get("/api/v1/projects", headers=admin_headers())
    assert first.status_code == 200
    assert second.status_code == 200
    assert third.status_code == 429
    assert third.headers["retry-after"] == "60"
    assert third.json()["detail"]["code"] == "rate_limited"


def test_expensive_endpoint_has_its_own_limit(client, settings):
    settings.rate_limit_requests_per_minute = 0
    settings.rate_limit_expensive_per_minute = 1
    payload = {"url": "https://shop.example.com/", "scope": {"type": "single_url"}}
    first = client.post("/api/v1/scans", headers=admin_headers(), json=payload)
    second = client.post("/api/v1/scans", headers=admin_headers(), json=payload)
    assert first.status_code == 200
    assert second.status_code == 429
    # A normal read is unaffected by the expensive bucket.
    assert client.get("/api/v1/projects", headers=admin_headers()).status_code == 200


def test_production_validation_is_fail_closed():
    from bugpilot_core.config import Settings

    from app.auth import validate_production

    with pytest.raises(RuntimeError):
        validate_production(Settings(bugpilot_env="production", auth_required=False))

    with pytest.raises(RuntimeError):
        validate_production(Settings(bugpilot_env="production", auth_required=True, api_keys=""))

    with pytest.raises(RuntimeError):
        validate_production(
            Settings(
                bugpilot_env="production",
                auth_required=True,
                api_keys="k:admin",
                evidence_signing_secret="",
            )
        )

    validate_production(
        Settings(
            bugpilot_env="production",
            auth_required=True,
            api_keys="k:admin",
            evidence_signing_secret="secret",
        )
    )