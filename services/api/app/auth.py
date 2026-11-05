"""Access control and rate limiting.

BugPilot is single-operator by default: authentication is off in development so
`localhost` works without setup. In production the server refuses to start
without keys, and every `/api/v1` request must present `X-API-Key` (or a
`token` query parameter for the WebSocket).

Two scopes exist:

* `admin` - everything
* `project:<id>` - only that project's scans, issues, reports and evidence

The limiter is a fixed one-minute window in process memory. That is honest for
a single API instance; a multi-instance deployment should move it to Redis.
"""

from __future__ import annotations

import hmac
import time
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from bugpilot_core.config import Settings
from fastapi import Request
from fastapi.responses import JSONResponse

PUBLIC_PATHS = {"/health", "/api/v1/health"}
# Evidence is authorized by its signed token instead of an API key.
PUBLIC_PREFIXES = ("/api/v1/evidence/",)
WS_SUFFIX = "/events"


@dataclass(frozen=True)
class Principal:
    key: str
    scope: str
    is_admin: bool

    @property
    def project_id(self) -> str | None:
        if self.scope.startswith("project:"):
            return self.scope.split(":", 1)[1]
        return None


class AuthError(Exception):
    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.message = message


def validate_production(settings: Settings) -> None:
    """Refuse to run a production API that is open or unsignable."""
    if not settings.is_production:
        return
    if not settings.auth_required:
        raise RuntimeError(
            "AUTH_REQUIRED must be enabled in production. Set AUTH_REQUIRED=true and API_KEYS."
        )
    if not settings.parsed_api_keys:
        raise RuntimeError("API_KEYS must be configured in production.")
    if not settings.evidence_signing_secret:
        raise RuntimeError("EVIDENCE_SIGNING_SECRET must be configured in production.")


def lookup_principal(settings: Settings, presented: str | None) -> Principal:
    if not presented:
        raise AuthError(401, "An API key is required. Send it in the X-API-Key header.")
    for key, scope in settings.parsed_api_keys.items():
        if hmac.compare_digest(key, presented):
            return Principal(key=key, scope=scope, is_admin=scope == "admin")
    raise AuthError(401, "The API key is not valid.")


def is_public(path: str) -> bool:
    if path in PUBLIC_PATHS:
        return True
    return any(path.startswith(prefix) for prefix in PUBLIC_PREFIXES)


def extract_key(request: Request) -> str | None:
    header = request.headers.get("x-api-key")
    if header:
        return header.strip()
    query = request.query_params.get("api_key")
    if query:
        return query.strip()
    return None


def require_project(principal: Principal, project_id: str | None) -> None:
    """Raise 403 when a project-scoped key touches another project."""
    if principal.is_admin or project_id is None:
        return
    allowed = principal.project_id
    if allowed and allowed != project_id:
        raise AuthError(403, "This API key is not authorized for that project.")


class RateLimiter:
    """Fixed-window per-minute limiter for one process."""

    def __init__(self) -> None:
        self._buckets: dict[tuple[str, str, int], int] = defaultdict(int)
        self._last_cleanup = 0.0

    def allow(self, identity: str, bucket: str, limit: int) -> tuple[bool, int]:
        if limit <= 0:
            return True, 0
        window = int(time.time() // 60)
        self._cleanup(window)
        key = (identity, bucket, window)
        self._buckets[key] += 1
        used = self._buckets[key]
        remaining = max(0, limit - used)
        return used <= limit, remaining

    def _cleanup(self, window: int) -> None:
        now = time.time()
        if now - self._last_cleanup < 30:
            return
        self._last_cleanup = now
        stale = [key for key in self._buckets if key[2] < window]
        for key in stale:
            self._buckets.pop(key, None)


def expensive_request(path: str, method: str) -> bool:
    """Scan creation and verification are the operations worth limiting."""
    if method == "POST" and path in {"/api/v1/scans"}:
        return True
    if method == "POST" and path.endswith("/verify-fix"):
        return True
    return False


def is_websocket(request: Request) -> bool:
    return request.scope.get("type") == "websocket"


def client_identity(request: Request, principal: Principal | None) -> str:
    if principal is not None:
        return f"key:{principal.key[:12]}"
    client = request.client.host if request.client else "unknown"
    return f"ip:{client}"


def unauthorized(message: str) -> JSONResponse:
    return JSONResponse(
        status_code=401,
        content={"detail": {"code": "unauthorized", "message": message, "details": None}},
    )


async def auth_middleware(request: Request, call_next: Any):
    settings: Settings = request.app.state.settings
    path = request.url.path

    if is_public(path) or not path.startswith(settings.api_prefix):
        return await call_next(request)

    principal: Principal | None = None
    if settings.auth_required or settings.parsed_api_keys:
        try:
            principal = lookup_principal(settings, extract_key(request))
        except AuthError as exc:
            return JSONResponse(
                status_code=exc.status_code,
                content={
                    "detail": {
                        "code": "unauthorized" if exc.status_code == 401 else "forbidden",
                        "message": exc.message,
                        "details": None,
                    }
                },
            )
    request.state.principal = principal

    limiter: RateLimiter = request.app.state.rate_limiter
    identity = client_identity(request, principal)
    allowed, remaining = limiter.allow(identity, "all", settings.rate_limit_requests_per_minute)
    if not allowed:
        return JSONResponse(
            status_code=429,
            headers={"Retry-After": "60", "X-RateLimit-Remaining": "0"},
            content={
                "detail": {
                    "code": "rate_limited",
                    "message": "Too many requests. Try again in a minute.",
                    "details": None,
                }
            },
        )
    if expensive_request(path, request.method):
        allowed, remaining = limiter.allow(identity, "expensive", settings.rate_limit_expensive_per_minute)
        if not allowed:
            return JSONResponse(
                status_code=429,
                headers={"Retry-After": "60", "X-RateLimit-Remaining": "0"},
                content={
                    "detail": {
                        "code": "rate_limited",
                        "message": "Too many scans or verifications. Try again in a minute.",
                        "details": None,
                    }
                },
            )

    if principal is not None:
        from fastapi import HTTPException

        from app.access import enforce_path_scope

        try:
            async with request.app.state.session_factory() as db:
                await enforce_path_scope(request, db)
        except HTTPException as exc:
            # Middleware runs outside the route handlers, so the app's
            # exception handlers never see this.
            return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

    response = await call_next(request)
    if settings.rate_limit_requests_per_minute > 0:
        response.headers["X-RateLimit-Remaining"] = str(remaining)
    return response


def principal_of(request: Request) -> Principal | None:
    return getattr(request.state, "principal", None)


def ensure_project_access(request: Request, project_id: str | None) -> None:
    """Raise an HTTP 403 for cross-project access by a project-scoped key."""
    from fastapi import HTTPException

    principal = principal_of(request)
    if principal is None:
        return
    try:
        require_project(principal, project_id)
    except AuthError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={"code": "forbidden", "message": exc.message, "details": None},
        ) from exc
