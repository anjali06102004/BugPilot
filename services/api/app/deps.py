from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any

from bugpilot_core.config import Settings, get_settings
from bugpilot_core.db import SessionLocal
from bugpilot_core.events import EventBus
from bugpilot_core.evidence import EvidenceStore, build_evidence_store
from fastapi import HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with SessionLocal() as db:
        yield db


def get_settings_dep() -> Settings:
    return get_settings()


def get_bus(request: Request) -> EventBus:
    return request.app.state.bus


def get_evidence_store(request: Request) -> EvidenceStore:
    return request.app.state.evidence_store


def build_evidence_store_once(settings: Settings) -> EvidenceStore:
    """One store per process so signed evidence URLs stay valid."""
    return build_evidence_store(settings)


class ApiError(HTTPException):
    def __init__(self, status_code: int, code: str, message: str, details: Any = None):
        super().__init__(
            status_code=status_code, detail={"code": code, "message": message, "details": details}
        )
        self.code = code
        self.message = message


def not_found(entity: str, identifier: str) -> ApiError:
    return ApiError(404, "not_found", f"{entity} '{identifier}' was not found.")


def bad_request(message: str, details: Any = None) -> ApiError:
    return ApiError(400, "bad_request", message, details)


def conflict(message: str, details: Any = None) -> ApiError:
    return ApiError(409, "conflict", message, details)


class PageParams:
    def __init__(self, limit: int = 50, offset: int = 0) -> None:
        self.limit = max(1, min(limit, 200))
        self.offset = max(0, offset)

    def as_dict(self) -> dict[str, Any]:
        return {"limit": self.limit, "offset": self.offset}


def pagination(limit: int = 50, offset: int = 0) -> PageParams:
    return PageParams(limit=limit, offset=offset)
