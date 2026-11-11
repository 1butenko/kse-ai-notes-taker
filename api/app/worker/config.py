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
    # Reads book pages whose PDF text garbles formulas or has none; empty turns it off.
    notes_vision_model: str = "google/gemini-3.7-flash"
    # The AI Note Taker agent (app/note_taker); its own variable so it never changes the
    # transcription model above.
    note_taker_model: str = "openai/gpt-5.5"
    # The app's API, which the AI Note Taker uses to fill the course (files, lectures, readings).
    api_url: str = "http://localhost:8000"
    quarto_bin: str = "quarto"
    quarto_concurrency: int = 4
    # The lecture-notes agent (app/note_taker/lecture_notes). Empty models use note_taker_model.
    lecture_notes_model: str = ""
    lecture_notes_reviewer_model: str = ""
    lecture_notes_max_renders: int = 12
    # Characters of reading text given to the agent per lecture; the rest is cut.
    lecture_notes_max_chars: int = 400_000
    # Lecture-notes runs at once on this worker.
    lecture_notes_concurrency: int = 2


@lru_cache
def get_worker_settings() -> WorkerSettings:
    return WorkerSettings()
