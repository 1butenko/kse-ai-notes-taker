from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "kse-ai-notes-taker"
    environment: str = "local"
    cors_origins: list[str] = ["http://localhost:3000"]
    uploads_dir: Path = Path("uploads")


settings = Settings()
