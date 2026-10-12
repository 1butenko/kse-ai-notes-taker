from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.session import session_dir


class WorkerSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=("../.env", ".env"), extra="ignore")

    environment: str = "local"
    uploads_root: Path = Field(Path("uploads"), validation_alias="uploads_dir")
    sessions: bool = False
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

    @property
    def uploads_dir(self) -> Path:
        return session_dir(self.uploads_root)


@lru_cache
def get_worker_settings() -> WorkerSettings:
    return WorkerSettings()
