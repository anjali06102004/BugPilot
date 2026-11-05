"""Database wiring.

The engine is created lazily so importing the models (for example from
Alembic) never opens a connection or requires an async driver. Schema
creation is handled by Alembic migrations, not by `create_all` at import time.
"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from bugpilot_core.config import get_settings

logger = logging.getLogger("bugpilot.db")

_engine: Any = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def make_engine(url: str | None = None):
    settings = get_settings()
    database_url = url or settings.database_url
    connect_args = {}
    if database_url.startswith("sqlite"):
        connect_args = {"check_same_thread": False}
    return create_async_engine(database_url, echo=False, connect_args=connect_args)


def get_engine():
    global _engine
    if _engine is None:
        _engine = make_engine()
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(get_engine(), expire_on_commit=False, class_=AsyncSession)
    return _session_factory


class _LazySessionLocal:
    """Callable that behaves like `async_sessionmaker` but defers engine
    creation until the first checkout."""

    def __call__(self) -> AsyncSession:
        return get_session_factory()()


SessionLocal = _LazySessionLocal()


def _migrations_dir() -> Path | None:
    override = os.environ.get("BUGPILOT_MIGRATIONS_DIR")
    if override:
        path = Path(override)
        return path if path.exists() else None
    root = Path(__file__).resolve().parents[4]
    candidate = root / "migrations"
    return candidate if candidate.exists() else None


def _sync_url(url: str) -> str:
    return url.replace("+aiosqlite", "").replace("+asyncpg", "").replace("+psycopg", "")


def run_migrations_sync(database_url: str | None = None) -> None:
    """Apply Alembic migrations synchronously (run from a worker thread)."""
    settings = get_settings()
    url = database_url or settings.database_url
    migrations = _migrations_dir()
    if migrations is None:
        logger.warning(
            "Migrations directory not found; creating tables with metadata.create_all. "
            "Set BUGPILOT_MIGRATIONS_DIR or ship the migrations directory in production."
        )
        from sqlalchemy import create_engine

        from bugpilot_core.db.models import Base

        engine = create_engine(_sync_url(url))
        Base.metadata.create_all(engine)
        engine.dispose()
        return

    from alembic import command
    from alembic.config import Config

    config = Config()
    config.set_main_option("script_location", str(migrations))
    config.set_main_option("sqlalchemy.url", _sync_url(url))
    command.upgrade(config, "head")


async def init_db() -> None:
    settings = get_settings()
    settings.evidence_dir.mkdir(parents=True, exist_ok=True)
    await asyncio.to_thread(run_migrations_sync, settings.database_url)
