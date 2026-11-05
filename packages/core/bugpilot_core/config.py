from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    bugpilot_env: str = "development"
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    web_origin: str = "http://localhost:3000"
    api_prefix: str = "/api/v1"
    cors_origins: str = ""

    database_url: str = "sqlite+aiosqlite:///./data/bugpilot.db"
    redis_url: str = "redis://localhost:6379/0"
    evidence_dir: Path = Path("./data/evidence")

    ai_provider: str = "gemini"
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.0-flash"
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    ai_send_page_text: bool = False

    allowed_host_suffixes: str = ""
    block_private_targets: bool = True
    max_pages_hard_limit: int = 100
    max_duration_seconds_hard_limit: int = 1200
    max_actions_hard_limit: int = 200
    max_model_calls_hard_limit: int = 80

    evidence_storage: str = "local"
    evidence_max_bytes: int = 5 * 1024 * 1024
    evidence_retention_days: int = 90
    redact_sensitive: bool = True
    evidence_signing_secret: str = ""
    evidence_public: bool = False

    scan_queue_key: str = "bugpilot:scans"
    event_channel_prefix: str = "bugpilot:scan:"
    event_history_limit: int = 2000
    worker_poll_seconds: float = 1.0

    # --- access control -------------------------------------------------
    # `API_KEYS` is a comma separated list of `key:scope` entries where scope
    # is `admin` or `project:<project_id>`.
    auth_required: bool = False
    api_keys: str = ""
    # Requests per minute per key/IP (0 disables the limiter).
    rate_limit_requests_per_minute: int = 0
    # Stricter limit for expensive actions: scan creation and verification.
    rate_limit_expensive_per_minute: int = 0

    # --- operations -----------------------------------------------------
    stale_scan_minutes: int = 30
    retention_check_interval_seconds: int = 86400
    metrics_enabled: bool = True
    log_json: bool = False

    @property
    def allowed_suffixes(self) -> list[str]:
        if not self.allowed_host_suffixes.strip():
            return []
        return [s.strip().lower() for s in self.allowed_host_suffixes.split(",") if s.strip()]

    @property
    def cors_origin_list(self) -> list[str]:
        origins = [self.web_origin, "http://localhost:3000", "http://127.0.0.1:3000"]
        if self.cors_origins.strip():
            origins.extend(s.strip() for s in self.cors_origins.split(",") if s.strip())
        seen: list[str] = []
        for origin in origins:
            if origin and origin not in seen:
                seen.append(origin)
        return seen

    @property
    def parsed_api_keys(self) -> dict[str, str]:
        """Map of API key -> scope (`admin` or `project:<id>`)."""
        keys: dict[str, str] = {}
        for entry in self.api_keys.split(","):
            entry = entry.strip()
            if not entry:
                continue
            if ":" in entry:
                key, _, scope = entry.partition(":")
                key = key.strip()
                scope = scope.strip() or "admin"
            else:
                key, scope = entry, "admin"
            if key:
                keys[key] = scope
        return keys

    @property
    def is_production(self) -> bool:
        return self.bugpilot_env.lower() == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
