"""Evidence retention.

Deleting artifacts is not the same as deleting the issue record: the registry
keeps its history, but the file is removed and the evidence row is marked as
purged so the UI never promises a screenshot it no longer has.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bugpilot_core.db.models import (
    FindingEvidence,
    IssueEvidence,
    Project,
    TestSession,
)
from bugpilot_core.evidence import EvidenceStore


async def purge_expired_evidence(
    db: AsyncSession,
    store: EvidenceStore,
    *,
    now: datetime | None = None,
    default_retention_days: int = 90,
) -> dict[str, Any]:
    now = now or datetime.now(UTC)
    projects = (await db.execute(select(Project))).scalars().all()
    removed_files = 0
    purged_rows = 0
    purged_paths: set[str] = set()

    for project in projects:
        days = project.evidence_retention_days
        if days is None:
            days = default_retention_days
        if days <= 0:
            # 0 means "keep forever" rather than "delete everything".
            continue
        cutoff = now - timedelta(days=days)
        sessions = (
            (await db.execute(select(TestSession.id).where(TestSession.project_id == project.id)))
            .scalars()
            .all()
        )
        for session_id in sessions:
            directory = store.settings.evidence_dir / session_id
            if not directory.exists():
                continue
            for path in directory.rglob("*"):
                if not path.is_file():
                    continue
                modified = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
                if modified >= cutoff:
                    continue
                try:
                    path.unlink()
                except OSError:
                    continue
                removed_files += 1
                purged_paths.add(str(path))

    if purged_paths:
        for model in (FindingEvidence, IssueEvidence):
            rows = (await db.execute(select(model).where(model.path.isnot(None)))).scalars().all()
            for row in rows:
                if row.path in purged_paths:
                    row.path = None
                    content = row.content if isinstance(row.content, dict) else {}
                    row.content = {**content, "purged": True, "purged_at": now.isoformat()}
                    purged_rows += 1
        await db.commit()

    return {
        "removed_files": removed_files,
        "purged_rows": purged_rows,
        "cutoff": now.isoformat(),
        "projects_checked": len(projects),
    }


def purge_empty_dirs(root: Path) -> int:
    """Remove empty session directories left behind by retention."""
    removed = 0
    if not root.exists():
        return 0
    for directory in sorted(root.iterdir(), reverse=True):
        if directory.is_dir() and not any(directory.iterdir()):
            directory.rmdir()
            removed += 1
    return removed
