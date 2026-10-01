from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from bugpilot_core.config import get_settings
from bugpilot_core.db.models import Base


def make_engine(url: str | None = None):
    settings = get_settings()
    database_url = url or settings.database_url
    connect_args = {}
    if database_url.startswith("sqlite"):
        connect_args = {"check_same_thread": False}
    return create_async_engine(database_url, echo=False, connect_args=connect_args)


engine = make_engine()
SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def init_db() -> None:
    settings = get_settings()
    settings.evidence_dir.mkdir(parents=True, exist_ok=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
