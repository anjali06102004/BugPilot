from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    bugpilot_env: str = "development"
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    web_origin: str = "http://localhost:3000"

    database_url: str = "sqlite+aiosqlite:///./data/bugpilot.db"
    redis_url: str = "redis://localhost:6379/0"
    evidence_dir: Path = Path("./data/evidence")

    ai_provider: str = "gemini"
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.0-flash"
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"

    allowed_host_suffixes: str = ""
    block_private_targets: bool = True
    max_pages_hard_limit: int = 100
    max_duration_seconds_hard_limit: int = 1200

    scan_queue_key: str = "bugpilot:scans"
    event_channel_prefix: str = "bugpilot:scan:"

    @property
    def allowed_suffixes(self) -> list[str]:
        if not self.allowed_host_suffixes.strip():
            return []
        return [s.strip().lower() for s in self.allowed_host_suffixes.split(",") if s.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
