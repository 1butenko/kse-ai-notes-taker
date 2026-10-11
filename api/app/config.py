from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=("../.env", ".env"), extra="ignore")

    app_name: str = "kse-ai-notes-taker"
    environment: str = "local"
    cors_origins: list[str] = ["http://localhost:3000"]
    cors_origin_regex: str | None = None
    uploads_dir: Path = Path("uploads")
    moodle_url: str
    moodle_token: str
    worker_url: str = "http://localhost:8001"


@lru_cache
def get_settings() -> Settings:
    return Settings()
