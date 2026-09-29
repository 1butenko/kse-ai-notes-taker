from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=("../.env", ".env"), extra="ignore")

    app_name: str = "kse-ai-notes-taker"
    environment: str = "local"
    cors_origins: list[str] = ["http://localhost:3000"]
    uploads_dir: Path = Path("uploads")
    moodle_url: str
    moodle_token: str
    openrouter_url: str = "https://openrouter.ai/api/v1"
    openrouter_api_key: str | None = None
    openrouter_model: str = "google/gemini-3.1-flash-lite"


@lru_cache
def get_settings() -> Settings:
    return Settings()
