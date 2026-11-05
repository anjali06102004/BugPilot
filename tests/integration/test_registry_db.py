"""Registry integration tests against a real (temporary) database.

These exercise the behaviour the product depends on: repeated scans reuse the
canonical issue, occurrences are preserved, and a fixed issue that reappears is
flagged as a regression.
"""

from __future__ import annotations

import uuid

import pytest
from bugpilot_core.db import SessionLocal, init_db
from bugpilot_core.db.models import Finding, Issue, IssueOccurrence, Project, TestSession
from bugpilot_core.models import (
    FindingCandidate,
    FindingCategory,
    IssueStatus,
    ScanStatus,
)
from bugpilot_core.registry import record_occurrence, transition_issue
from sqlalchemy import select


async def make_context(db):
    project = Project(
        id=str(uuid.uuid4()),
        name="Registry test",
        website_url="https://shop.example.com/",
        environment="staging",
    )
    session = TestSession(
        id=str(uuid.uuid4()),
        project_id=project.id,
        start_url="https://shop.example.com/cart",
        status=ScanStatus.COMPLETED.value,
        scope_type="single_url",
        scope_json={"type": "single_url", "start_url": "https://shop.example.com/cart"},
        config_json={},
    )
    db.add(project)
    db.add(session)
    await db.commit()
    return project, session


def make_candidate() -> FindingCandidate:
    return FindingCandidate(
        category=FindingCategory.OVERFLOW,
        title="Horizontal overflow on page",
        description="The page scrolls sideways on mobile.",
        confidence=0.95,
        source="overflow_detector",
        url="https://shop.example.com/cart",
        fingerprint="overflow-fp",
        error_signature="h-overflow:390",
        expected="Content fits the viewport.",
        actual="scrollWidth 1400 > clientWidth 390",
    )


async def add_finding(db, session) -> Finding:
    finding = Finding(
        id=str(uuid.uuid4()),
        session_id=session.id,
        category="overflow",
        title="Horizontal overflow on page",
        description="The page scrolls sideways on mobile.",
        severity="medium",
        priority="P2",
        confidence=0.95,
        confidence_label="confirmed",
        status="verified",
        source="overflow_detector",
        url="https://shop.example.com/cart",
        route="/cart",
        fingerprint="overflow-fp",
        extra={"reproduced": True},
    )
    db.add(finding)
    await db.commit()
    return finding


@pytest.mark.asyncio
async def test_repeated_scan_reuses_issue_and_keeps_occurrences():
    await init_db()
    async with SessionLocal() as db:
        project, session1 = await make_context(db)
        session2 = TestSession(
            id=str(uuid.uuid4()),
            project_id=project.id,
            start_url=session1.start_url,
            status=ScanStatus.COMPLETED.value,
            scope_type="single_url",
            scope_json=session1.scope_json,
            config_json={},
        )
        db.add(session2)
        await db.commit()

        finding1 = await add_finding(db, session1)
        issue1, created1, _reg1 = await record_occurrence(
            db,
            session=session1,
            finding=finding1,
            candidate=make_candidate(),
            severity="medium",
            priority="P2",
            confidence_label="confirmed",
            confidence=0.95,
        )
        await db.commit()

        finding2 = await add_finding(db, session2)
        issue2, created2, _reg2 = await record_occurrence(
            db,
            session=session2,
            finding=finding2,
            candidate=make_candidate(),
            severity="medium",
            priority="P2",
            confidence_label="confirmed",
            confidence=0.95,
        )
        await db.commit()

        assert created1 is True
        assert created2 is False
        assert issue1.id == issue2.id
        occurrences = (
            (await db.execute(select(IssueOccurrence).where(IssueOccurrence.issue_id == issue1.id)))
            .scalars()
            .all()
        )
        assert len(occurrences) == 2
        assert {o.session_id for o in occurrences} == {session1.id, session2.id}
        assert issue2.occurrence_count == 2


@pytest.mark.asyncio
async def test_fixed_issue_that_reappears_is_a_regression():
    await init_db()
    async with SessionLocal() as db:
        project, session = await make_context(db)
        finding = await add_finding(db, session)
        issue, _created, _reg = await record_occurrence(
            db,
            session=session,
            finding=finding,
            candidate=make_candidate(),
            severity="medium",
            priority="P2",
            confidence_label="confirmed",
            confidence=0.95,
        )
        await db.commit()

        await transition_issue(db, issue, IssueStatus.TRIAGED)
        await transition_issue(db, issue, IssueStatus.CONFIRMED)
        await transition_issue(db, issue, IssueStatus.IN_PROGRESS)
        await transition_issue(db, issue, IssueStatus.FIXED)
        await transition_issue(db, issue, IssueStatus.VERIFIED)
        await db.commit()
        assert issue.status == "verified"

        again = TestSession(
            id=str(uuid.uuid4()),
            project_id=project.id,
            start_url=session.start_url,
            status=ScanStatus.COMPLETED.value,
            scope_type="single_url",
            scope_json=session.scope_json,
            config_json={},
        )
        db.add(again)
        await db.commit()
        finding2 = await add_finding(db, again)
        issue2, _created2, regression = await record_occurrence(
            db,
            session=again,
            finding=finding2,
            candidate=make_candidate(),
            severity="medium",
            priority="P2",
            confidence_label="confirmed",
            confidence=0.95,
        )
        await db.commit()

        assert regression is True
        assert issue2.status == IssueStatus.REOPENED.value
        assert issue2.is_regression is True
        assert issue2.reopened_count == 1


@pytest.mark.asyncio
async def test_distinct_bugs_do_not_merge():
    await init_db()
    async with SessionLocal() as db:
        project, session = await make_context(db)
        first = make_candidate()
        second = first.model_copy(
            update={"fingerprint": "another-fp", "error_signature": "content:clip:other"}
        )
        finding1 = await add_finding(db, session)
        finding2 = await add_finding(db, session)
        issue1, _c1, _r1 = await record_occurrence(
            db,
            session=session,
            finding=finding1,
            candidate=first,
            severity="medium",
            priority="P2",
            confidence_label="confirmed",
            confidence=0.95,
        )
        issue2, _c2, _r2 = await record_occurrence(
            db,
            session=session,
            finding=finding2,
            candidate=second,
            severity="medium",
            priority="P2",
            confidence_label="confirmed",
            confidence=0.95,
        )
        await db.commit()
        assert issue1.id != issue2.id
        total = (await db.execute(select(Issue).where(Issue.project_id == project.id))).scalars().all()
        assert len(total) == 2
