from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.session import session_dir


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=("../.env", ".env"), extra="ignore")

    app_name: str = "kse-ai-notes-taker"
    environment: str = "local"
    cors_origins: list[str] = ["http://localhost:3000"]
    cors_origin_regex: str | None = None
    uploads_root: Path = Field(Path("uploads"), validation_alias="uploads_dir")
    sessions: bool = False
    session_ttl_minutes: int = 120
    moodle_url: str
    moodle_token: str
    worker_url: str = "http://localhost:8001"

    @property
    def uploads_dir(self) -> Path:
        return session_dir(self.uploads_root)


@lru_cache
def get_settings() -> Settings:
    return Settings()
