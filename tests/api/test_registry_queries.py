"""Phase 3 contracts: registry search, trends, bulk triage, duplicates, exports."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from app.main import app
from bugpilot_core.db import SessionLocal, init_db
from bugpilot_core.db.models import Issue, IssueOccurrence, Project
from fastapi.testclient import TestClient

SEEDED: dict[str, object] = {}


async def seed() -> dict[str, object]:
    if SEEDED:
        return SEEDED
    await init_db()
    now = datetime.now(UTC)
    async with SessionLocal() as db:
        project = Project(
            id=str(uuid.uuid4()),
            name="Registry queries",
            website_url="https://shop.example.com/",
            environment="staging",
        )
        db.add(project)

        def make(title, severity, priority, status, **extra):
            issue = Issue(
                id=str(uuid.uuid4()),
                issue_key=f"key-{uuid.uuid4().hex}",
                project_id=project.id,
                title=title,
                summary=f"{title} summary",
                description=f"{title} description",
                category=extra.get("category", "layout"),
                severity=severity,
                priority=priority,
                confidence_label=extra.get("confidence_label", "confirmed"),
                confidence=0.9,
                status=status,
                source="layout_detector",
                url="https://shop.example.com/cart",
                route="/cart",
                fingerprint=extra.get("fingerprint"),
                selector=extra.get("selector"),
                error_signature=extra.get("error_signature"),
                occurrence_count=extra.get("occurrence_count", 1),
                affected_scan_count=extra.get("occurrence_count", 1),
                is_regression=extra.get("is_regression", False),
                assigned_to=extra.get("assigned_to"),
                first_seen_at=extra.get("first_seen_at", now),
                last_seen_at=now,
            )
            db.add(issue)
            return issue

        critical = make("Checkout button overlaps total", "critical", "P1", "new", category="layout")
        high = make(
            "Cart API returns 500",
            "high",
            "P0",
            "in_progress",
            category="network",
            occurrence_count=4,
            is_regression=True,
            assigned_to="dev@example.com",
            fingerprint="fp-network",
            first_seen_at=now - timedelta(days=10),
        )
        medium = make("Image missing alt text", "medium", "P2", "fixed", category="accessibility")
        low = make(
            "Footer text clipped",
            "low",
            "P3",
            "closed",
            category="content",
            occurrence_count=2,
            fingerprint="fp-dupe",
        )
        dupe_candidate = make(
            "Footer text clipped on mobile",
            "low",
            "P3",
            "new",
            category="content",
            fingerprint="fp-dupe",
        )
        await db.flush()

        db.add(
            IssueOccurrence(
                id=str(uuid.uuid4()),
                issue_id=critical.id,
                session_id="scan-alpha",
                url="https://shop.example.com/cart",
                severity="critical",
                priority="P1",
                confidence=0.9,
                confidence_label="confirmed",
            )
        )
        db.add(
            IssueOccurrence(
                id=str(uuid.uuid4()),
                issue_id=high.id,
                session_id="scan-beta",
                url="https://shop.example.com/api/cart",
                severity="high",
                priority="P0",
                confidence=0.93,
                confidence_label="confirmed",
                verified=True,
                reproduced=True,
            )
        )
        await db.commit()
        SEEDED.update(
            project_id=project.id,
            critical=critical.id,
            high=high.id,
            medium=medium.id,
            low=low.id,
            dupe_candidate=dupe_candidate.id,
        )
        return SEEDED


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as test_client:
        yield test_client


def ids(data: dict) -> set[str]:
    return {item["id"] for item in data["items"]}


def test_filters_are_applied_in_sql_and_total_is_correct(client):
    seeded = asyncio.run(seed())
    project_id = seeded["project_id"]

    response = client.get(f"/api/v1/issues?project_id={project_id}&limit=2")
    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 5
    assert len(payload["items"]) == 2

    page_two = client.get(f"/api/v1/issues?project_id={project_id}&limit=2&offset=2").json()
    assert len(page_two["items"]) == 2
    assert ids(payload).isdisjoint(ids(page_two))


def test_severity_and_status_filters(client):
    seeded = asyncio.run(seed())
    project_id = seeded["project_id"]
    critical = client.get(f"/api/v1/issues?project_id={project_id}&severity=critical").json()
    assert ids(critical) == {seeded["critical"]}

    open_only = client.get(f"/api/v1/issues?project_id={project_id}&status=in_progress").json()
    assert ids(open_only) == {seeded["high"]}


def test_recurring_and_regression_filters(client):
    seeded = asyncio.run(seed())
    project_id = seeded["project_id"]
    recurring = client.get(f"/api/v1/issues?project_id={project_id}&recurring=true").json()
    assert {seeded["high"], seeded["low"]}.issubset(ids(recurring))

    regressions = client.get(f"/api/v1/issues?project_id={project_id}&regression=true").json()
    assert ids(regressions) == {seeded["high"]}


def test_scan_filter_and_owner_and_date_filters(client):
    seeded = asyncio.run(seed())
    project_id = seeded["project_id"]
    by_scan = client.get("/api/v1/issues?scan_id=scan-alpha").json()
    assert ids(by_scan) == {seeded["critical"]}

    by_owner = client.get("/api/v1/issues?assigned_to=dev@example.com").json()
    assert seeded["high"] in ids(by_owner)

    future = (datetime.now(UTC) + timedelta(days=2)).date().isoformat()
    none_recent = client.get(f"/api/v1/issues?project_id={project_id}&first_seen_after={future}").json()
    assert none_recent["total"] == 0


def test_sorting_puts_most_severe_first(client):
    seeded = asyncio.run(seed())
    project_id = seeded["project_id"]
    payload = client.get(f"/api/v1/issues?project_id={project_id}&sort=severity&order=asc").json()
    severities = [item["severity"] for item in payload["items"]]
    assert severities[0] == "critical"
    assert severities[-1] in {"low", "informational"}

    priority = client.get(f"/api/v1/issues?project_id={project_id}&sort=priority&order=asc").json()
    assert priority["items"][0]["priority"] == "P0"


def test_grouping_reports_full_counts_not_page_counts(client):
    seeded = asyncio.run(seed())
    project_id = seeded["project_id"]
    payload = client.get(f"/api/v1/issues?project_id={project_id}&group_by=severity&limit=1").json()
    assert payload["group_counts"] == {
        "critical": 1,
        "high": 1,
        "medium": 1,
        "low": 2,
    }
    # Grouping covers the whole filtered set even when the page is limited.
    assert sum(len(items) for items in payload["groups"].values()) == 5


def test_group_by_rejects_unknown_fields(client):
    response = client.get("/api/v1/issues?group_by=password")
    assert response.status_code == 400


def test_trends_shape_and_totals(client):
    asyncio.run(seed())
    payload = client.get("/api/v1/issues/trends?days=14").json()
    assert payload["days"] == 14
    assert len(payload["points"]) == 14
    assert {"date", "new", "resolved", "reopened"} <= set(payload["points"][0])
    assert payload["totals"]["new"] >= 1


def test_bulk_transition_reports_partial_failure(client):
    seeded = asyncio.run(seed())
    # critical is `new` (can move to triaged); medium is `fixed` (cannot).
    response = client.post(
        "/api/v1/issues/bulk",
        json={
            "issue_ids": [seeded["critical"], seeded["medium"]],
            "action": "transition",
            "status": "triaged",
            "author": "qa",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["updated"] == 1
    assert payload["failed"] == 1
    failed = [r for r in payload["results"] if not r["ok"]]
    assert failed[0]["id"] == seeded["medium"]
    assert "invalid transition" in failed[0]["error"]


def test_bulk_assign_and_label(client):
    seeded = asyncio.run(seed())
    assigned = client.post(
        "/api/v1/issues/bulk",
        json={
            "issue_ids": [seeded["critical"], seeded["low"]],
            "action": "assign",
            "assignee": "triage@example.com",
        },
    ).json()
    assert assigned["updated"] == 2

    labelled = client.post(
        "/api/v1/issues/bulk",
        json={
            "issue_ids": [seeded["critical"]],
            "action": "label",
            "labels": ["release-blocker", "mobile"],
        },
    ).json()
    assert labelled["updated"] == 1
    issue = client.get(f"/api/v1/issues/{seeded['critical']}").json()
    assert issue["labels"] == ["release-blocker", "mobile"]


def test_bulk_rejects_empty_and_oversized_batches(client):
    assert client.post("/api/v1/issues/bulk", json={"issue_ids": [], "action": "assign"}).status_code == 400
    oversized = [str(uuid.uuid4()) for _ in range(201)]
    assert (
        client.post("/api/v1/issues/bulk", json={"issue_ids": oversized, "action": "assign"}).status_code
        == 400
    )


def test_duplicate_suggestions_and_merge(client):
    seeded = asyncio.run(seed())
    suggestions = client.get(f"/api/v1/issues/{seeded['low']}/duplicates").json()
    assert suggestions["total"] >= 1
    match = next(item for item in suggestions["items"] if item["id"] == seeded["dupe_candidate"])
    assert match["score"] >= 0.35
    assert any("fingerprint" in reason for reason in match["reasons"])

    merged = client.post(
        f"/api/v1/issues/{seeded['low']}/merge",
        json={"source_issue_id": seeded["dupe_candidate"], "author": "qa"},
    )
    assert merged.status_code == 200
    source = client.get(f"/api/v1/issues/{seeded['dupe_candidate']}").json()
    assert source["status"] == "duplicate"


def test_project_markdown_and_pdf_exports(client):
    seeded = asyncio.run(seed())
    markdown = client.get(f"/api/v1/reports/project/{seeded['project_id']}.md")
    assert markdown.status_code == 200
    assert "BugPilot report" in markdown.text
    assert "Cart API returns 500" in markdown.text
    assert "not a statement that the application is free of other defects" in markdown.text

    pdf = client.get(f"/api/v1/reports/project/{seeded['project_id']}.pdf")
    assert pdf.status_code == 200
    assert pdf.headers["content-type"] == "application/pdf"
    assert pdf.content.startswith(b"%PDF-")


def test_issue_markdown_export(client):
    seeded = asyncio.run(seed())
    response = client.get(f"/api/v1/reports/issue/{seeded['high']}.md")
    assert response.status_code == 200
    body = response.text
    assert "Cart API returns 500" in body
    assert "Occurrence history" in body
    assert "hypotheses unless marked confirmed" in body
