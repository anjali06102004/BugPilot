"""Alembic environment.

Migrations run against a synchronous driver so they work the same way locally
(SQLite) and in production (PostgreSQL). The async engine used by the app is
converted to its sync equivalent here.
"""

from __future__ import annotations

import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

ROOT = Path(__file__).resolve().parent.parent
for candidate in (ROOT / "packages" / "core",):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from bugpilot_core.config import get_settings  # noqa: E402
from bugpilot_core.db.models import Base  # noqa: E402

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _sync_url() -> str:
    url = config.get_main_option("sqlalchemy.url") or get_settings().database_url
    return (
        url.replace("+aiosqlite", "")
        .replace("+asyncpg", "")
        .replace("+psycopg", "")
    )


def run_migrations_offline() -> None:
    context.configure(
        url=_sync_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    section = config.get_section(config.config_ini_section, {})
    section["sqlalchemy.url"] = _sync_url()
    connectable = engine_from_config(
        section, prefix="sqlalchemy.", poolclass=pool.NullPool
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()