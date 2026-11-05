from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    website_url: Mapped[str] = mapped_column(String(2000))
    environment: Mapped[str] = mapped_column(String(32), default="staging")
    description: Mapped[str] = mapped_column(Text, default="")
    critical_routes: Mapped[list[str]] = mapped_column(JSON, default=list)
    evidence_retention_days: Mapped[int] = mapped_column(Integer, default=90)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    sessions: Mapped[list[TestSession]] = relationship(back_populates="project")
    issues: Mapped[list[Issue]] = relationship(back_populates="project")

    __table_args__ = (Index("ix_projects_name", "name"),)


class TestSession(Base):
    __tablename__ = "test_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"))
    start_url: Mapped[str] = mapped_column(String(2000))
    status: Mapped[str] = mapped_column(String(32), default="queued")
    scope_type: Mapped[str] = mapped_column(String(32), default="full_site")
    scope_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    config_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    stop_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    pages_tested: Mapped[int] = mapped_column(Integer, default=0)
    actions_taken: Mapped[int] = mapped_column(Integer, default=0)
    model_calls: Mapped[int] = mapped_column(Integer, default=0)
    pages_skipped: Mapped[int] = mapped_column(Integer, default=0)
    idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True, unique=True)
    requested_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    project: Mapped[Project] = relationship(back_populates="sessions")
    pages: Mapped[list[PageRecord]] = relationship(back_populates="session")
    findings: Mapped[list[Finding]] = relationship(back_populates="session")
    actions: Mapped[list[ActionRecord]] = relationship(back_populates="session")
    events_note: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index("ix_test_sessions_status", "status"),
        Index("ix_test_sessions_project", "project_id"),
        Index("ix_test_sessions_created", "created_at"),
    )


class PageRecord(Base):
    __tablename__ = "pages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("test_sessions.id"))
    url: Mapped[str] = mapped_column(String(2000))
    title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    viewport_name: Mapped[str] = mapped_column(String(64))
    screenshot_path: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    in_scope: Mapped[bool] = mapped_column(Boolean, default=True)
    skip_reason: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    session: Mapped[TestSession] = relationship(back_populates="pages")


class ActionRecord(Base):
    __tablename__ = "actions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("test_sessions.id"))
    type: Mapped[str] = mapped_column(String(64))
    description: Mapped[str] = mapped_column(Text)
    selector: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    url: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    blocked: Mapped[int] = mapped_column(Integer, default=0)
    block_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    session: Mapped[TestSession] = relationship(back_populates="actions")


class Observation(Base):
    __tablename__ = "observations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("test_sessions.id"))
    url: Mapped[str] = mapped_column(String(2000))
    summary: Mapped[str] = mapped_column(Text, default="")
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Finding(Base):
    """A defect observed during one scan. Occurrences of an issue each get
    their own row; the canonical record lives in `Issue`."""

    __tablename__ = "findings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("test_sessions.id"))
    issue_id: Mapped[str | None] = mapped_column(ForeignKey("issues.id"), nullable=True)
    category: Mapped[str] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(500))
    description: Mapped[str] = mapped_column(Text)
    severity: Mapped[str] = mapped_column(String(32))
    priority: Mapped[str] = mapped_column(String(8), default="P3")
    confidence: Mapped[float] = mapped_column(Float)
    confidence_label: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(32), default="new")
    source: Mapped[str] = mapped_column(String(128))
    url: Mapped[str] = mapped_column(String(2000))
    route: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    component: Mapped[str | None] = mapped_column(String(500), nullable=True)
    selector: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    fingerprint: Mapped[str | None] = mapped_column(String(128), nullable=True)
    expected: Mapped[str | None] = mapped_column(Text, nullable=True)
    actual: Mapped[str | None] = mapped_column(Text, nullable=True)
    steps_json: Mapped[list[Any]] = mapped_column(JSON, default=list)
    suggested_fix: Mapped[str | None] = mapped_column(Text, nullable=True)
    root_cause: Mapped[str | None] = mapped_column(Text, nullable=True)
    reproduced_count: Mapped[int] = mapped_column(Integer, default=0)
    verification_attempts: Mapped[int] = mapped_column(Integer, default=0)
    screenshot_path: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    extra: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    session: Mapped[TestSession] = relationship(back_populates="findings")
    evidence: Mapped[list[FindingEvidence]] = relationship(back_populates="finding")
    verifications: Mapped[list[VerificationRun]] = relationship(back_populates="finding")
    issue: Mapped[Issue | None] = relationship(back_populates="findings")

    __table_args__ = (
        Index("ix_findings_session", "session_id"),
        Index("ix_findings_issue", "issue_id"),
        Index("ix_findings_severity", "severity"),
    )


class FindingEvidence(Base):
    __tablename__ = "finding_evidence"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    finding_id: Mapped[str] = mapped_column(ForeignKey("findings.id"))
    kind: Mapped[str] = mapped_column(String(64))
    path: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    content: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    finding: Mapped[Finding] = relationship(back_populates="evidence")


class VerificationRun(Base):
    __tablename__ = "verification_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    finding_id: Mapped[str] = mapped_column(ForeignKey("findings.id"))
    reproduced: Mapped[int] = mapped_column(Integer, default=0)
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    finding: Mapped[Finding] = relationship(back_populates="verifications")


class Issue(Base):
    """Canonical, persistent record in the Bug Registry.

    One row per distinct defect. Every scan that observes the defect adds an
    `IssueOccurrence` instead of creating a new issue.
    """

    __tablename__ = "issues"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    issue_key: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"))
    title: Mapped[str] = mapped_column(String(500))
    summary: Mapped[str] = mapped_column(Text, default="")
    description: Mapped[str] = mapped_column(Text, default="")
    category: Mapped[str] = mapped_column(String(64))
    severity: Mapped[str] = mapped_column(String(32), default="medium")
    priority: Mapped[str] = mapped_column(String(8), default="P3")
    confidence_label: Mapped[str] = mapped_column(String(32), default="possible")
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(32), default="new")
    source: Mapped[str] = mapped_column(String(128), default="")
    url: Mapped[str] = mapped_column(String(2000), default="")
    route: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    component: Mapped[str | None] = mapped_column(String(500), nullable=True)
    selector: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    fingerprint: Mapped[str | None] = mapped_column(String(128), nullable=True)
    error_signature: Mapped[str | None] = mapped_column(String(256), nullable=True)
    expected: Mapped[str | None] = mapped_column(Text, nullable=True)
    actual: Mapped[str | None] = mapped_column(Text, nullable=True)
    preconditions: Mapped[str | None] = mapped_column(Text, nullable=True)
    reproduction_steps: Mapped[list[Any]] = mapped_column(JSON, default=list)
    root_cause: Mapped[str | None] = mapped_column(Text, nullable=True)
    root_cause_status: Mapped[str] = mapped_column(String(32), default="unconfirmed")
    suggested_fix: Mapped[str | None] = mapped_column(Text, nullable=True)
    business_impact: Mapped[str | None] = mapped_column(Text, nullable=True)
    environment: Mapped[str | None] = mapped_column(String(32), nullable=True)
    browser: Mapped[str | None] = mapped_column(String(32), nullable=True)
    viewport: Mapped[str | None] = mapped_column(String(64), nullable=True)
    assigned_to: Mapped[str | None] = mapped_column(String(128), nullable=True)
    labels: Mapped[list[str]] = mapped_column(JSON, default=list)
    is_regression: Mapped[bool] = mapped_column(Boolean, default=False)
    occurrence_count: Mapped[int] = mapped_column(Integer, default=0)
    affected_scan_count: Mapped[int] = mapped_column(Integer, default=0)
    affected_page_count: Mapped[int] = mapped_column(Integer, default=1)
    verified_count: Mapped[int] = mapped_column(Integer, default=0)
    reopened_count: Mapped[int] = mapped_column(Integer, default=0)
    extra: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    project: Mapped[Project] = relationship(back_populates="issues")
    occurrences: Mapped[list[IssueOccurrence]] = relationship(back_populates="issue")
    events: Mapped[list[IssueEvent]] = relationship(back_populates="issue")
    evidence: Mapped[list[IssueEvidence]] = relationship(back_populates="issue")
    verifications: Mapped[list[IssueVerification]] = relationship(back_populates="issue")
    findings: Mapped[list[Finding]] = relationship(back_populates="issue")

    __table_args__ = (
        Index("ix_issues_project", "project_id"),
        Index("ix_issues_severity", "severity"),
        Index("ix_issues_priority", "priority"),
        Index("ix_issues_status", "status"),
        Index("ix_issues_last_seen", "last_seen_at"),
    )


class IssueOccurrence(Base):
    """One sighting of an issue in one scan. Kept separate from the canonical
    record so historical evidence is never overwritten."""

    __tablename__ = "issue_occurrences"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    issue_id: Mapped[str] = mapped_column(ForeignKey("issues.id"))
    session_id: Mapped[str] = mapped_column(ForeignKey("test_sessions.id"))
    finding_id: Mapped[str | None] = mapped_column(ForeignKey("findings.id"), nullable=True)
    url: Mapped[str] = mapped_column(String(2000), default="")
    route: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    viewport: Mapped[str | None] = mapped_column(String(64), nullable=True)
    severity: Mapped[str] = mapped_column(String(32), default="medium")
    priority: Mapped[str] = mapped_column(String(8), default="P3")
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    confidence_label: Mapped[str] = mapped_column(String(32), default="possible")
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    reproduced: Mapped[bool] = mapped_column(Boolean, default=False)
    evidence: Mapped[list[Any]] = mapped_column(JSON, default=list)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    issue: Mapped[Issue] = relationship(back_populates="occurrences")

    __table_args__ = (
        UniqueConstraint("issue_id", "session_id", "finding_id", name="uq_occurrence"),
        Index("ix_occurrences_issue", "issue_id"),
        Index("ix_occurrences_session", "session_id"),
    )


class IssueEvent(Base):
    """Audit trail for a canonical issue: status changes, notes, assignments."""

    __tablename__ = "issue_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    issue_id: Mapped[str] = mapped_column(ForeignKey("issues.id"))
    kind: Mapped[str] = mapped_column(String(32), default="note")
    from_value: Mapped[str | None] = mapped_column(String(200), nullable=True)
    to_value: Mapped[str | None] = mapped_column(String(200), nullable=True)
    body: Mapped[str] = mapped_column(Text, default="")
    author: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    issue: Mapped[Issue] = relationship(back_populates="events")

    __table_args__ = (Index("ix_issue_events_issue", "issue_id"),)


class IssueEvidence(Base):
    """Evidence linked directly to a canonical issue, independent of any single
    scan occurrence."""

    __tablename__ = "issue_evidence"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    issue_id: Mapped[str] = mapped_column(ForeignKey("issues.id"))
    occurrence_id: Mapped[str | None] = mapped_column(ForeignKey("issue_occurrences.id"), nullable=True)
    session_id: Mapped[str | None] = mapped_column(ForeignKey("test_sessions.id"), nullable=True)
    kind: Mapped[str] = mapped_column(String(64))
    path: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    content: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    redacted: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    issue: Mapped[Issue] = relationship(back_populates="evidence")

    __table_args__ = (Index("ix_issue_evidence_issue", "issue_id"),)


class WorkerHeartbeat(Base):
    """Liveness and throughput for each browser worker.

    The API exposes the age of the newest heartbeat so an operator can tell a
    dead worker from an idle queue without reading container logs.
    """

    __tablename__ = "worker_heartbeats"

    worker_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    status: Mapped[str] = mapped_column(String(32), default="idle")
    scans_processed: Mapped[int] = mapped_column(Integer, default=0)
    event_transport: Mapped[str] = mapped_column(String(32), default="database")
    extra: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ScanEventRow(Base):
    """Durable scan event log.

    Redis pub/sub is used when it is available. The table is the fallback so
    the API and the browser worker still share one event stream in local
    development without a Redis server.
    """

    __tablename__ = "scan_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String(36))
    type: Mapped[str] = mapped_column(String(64))
    message: Mapped[str] = mapped_column(Text, default="")
    mascot: Mapped[str] = mapped_column(String(32), default="exploring")
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (Index("ix_scan_events_session_id", "session_id"),)


class IssueVerification(Base):
    """Result of a post-fix verification run.

    Kept separate from scan-time findings because the question is different:
    "does the defect still reproduce now that someone changed the code?"
    """

    __tablename__ = "issue_verifications"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    issue_id: Mapped[str] = mapped_column(ForeignKey("issues.id"))
    verdict: Mapped[str] = mapped_column(String(32))
    method: Mapped[str] = mapped_column(String(64), default="replay")
    notes: Mapped[str] = mapped_column(Text, default="")
    evidence_path: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    actions_replayed: Mapped[int] = mapped_column(Integer, default=0)
    actions_failed: Mapped[int] = mapped_column(Integer, default=0)
    created_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    issue: Mapped[Issue] = relationship(back_populates="verifications")

    __table_args__ = (Index("ix_issue_verifications_issue", "issue_id"),)


class AgentRun(Base):
    __tablename__ = "agent_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("test_sessions.id"))
    status: Mapped[str] = mapped_column(String(32))
    graph_version: Mapped[str] = mapped_column(String(64), default="exploration_agent_v1")
    extra: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ModelRun(Base):
    __tablename__ = "model_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("test_sessions.id"))
    prompt_name: Mapped[str] = mapped_column(String(128))
    prompt_version: Mapped[str] = mapped_column(String(32))
    provider: Mapped[str] = mapped_column(String(64))
    model: Mapped[str] = mapped_column(String(128))
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    valid_output: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (Index("ix_model_runs_session", "session_id"),)
