from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class WorkerSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=("../.env", ".env"), extra="ignore")

    environment: str = "local"
    uploads_dir: Path = Path("uploads")
    openrouter_url: str = "https://openrouter.ai/api/v1"
    openrouter_api_key: str | None = None
    openrouter_model: str = "google/gemini-3.1-flash-lite"
    langfuse_public_key: str | None = None
    langfuse_secret_key: str | None = None
    langfuse_base_url: str = "http://localhost:3001"


@lru_cache
def get_worker_settings() -> WorkerSettings:
    return WorkerSettings()
