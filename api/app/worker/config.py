from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

from app.config import PublicAPIURL


class WorkerSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=("../.env", ".env"), extra="ignore")

    public_api_url: PublicAPIURL = "http://localhost:8000"
    environment: str = "local"
    uploads_dir: Path = Path("uploads")
    openrouter_url: str = "https://openrouter.ai/api/v1"
    openrouter_api_key: str | None = None
    openrouter_model: str = "google/gemini-3.1-flash-lite"
    notes_planner_model: str = "openai/gpt-6.1-sol"
    notes_selector_model: str = "openai/gpt-6-luna"
    notes_writer_model: str = "google/gemini-3.7-flash"
    notes_verifier_model: str = "openai/gpt-6-luna"
    notes_escalation_model: str = "openai/gpt-6.1-sol"
    notes_concurrency: int = 4
    notes_plan_rounds: int = 3
    notes_revision_rounds: int = 2
    quarto_bin: str = "quarto"
    quarto_concurrency: int = 4
    langfuse_public_key: str | None = None
    langfuse_secret_key: str | None = None
    langfuse_base_url: str = "http://localhost:3001"


@lru_cache
def get_worker_settings() -> WorkerSettings:
    return WorkerSettings()
