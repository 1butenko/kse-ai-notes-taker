from functools import lru_cache
from pathlib import Path
from typing import Annotated
from urllib.parse import quote, urlsplit, urlunsplit

from pydantic import AfterValidator
from pydantic_settings import BaseSettings, SettingsConfigDict


def validate_public_api_url(value: str) -> str:
    parsed = urlsplit(value)
    if (
        parsed.scheme not in ("http", "https")
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or any(char.isspace() for char in value)
        or any(c in value for c in '<>"\\')
    ):
        raise ValueError(
            "PUBLIC_API_URL must be an HTTP(S) base URL without credentials, query or fragment"
        )
    try:
        _ = parsed.port
    except ValueError as error:
        raise ValueError("Invalid PUBLIC_API_URL port") from error
    path = quote(parsed.path.rstrip("/"), safe="/%:@-._~!$&'*+,;=")
    return urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))


PublicAPIURL = Annotated[str, AfterValidator(validate_public_api_url)]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=("../.env", ".env"), extra="ignore")

    app_name: str = "kse-ai-notes-taker"
    environment: str = "local"
    cors_origins: list[str] = ["http://localhost:3000"]
    cors_origin_regex: str | None = None
    uploads_dir: Path = Path("uploads")
    moodle_url: str
    moodle_token: str
    public_api_url: PublicAPIURL = "http://localhost:8000"
    worker_url: str = "http://localhost:8001"

    # AI Note Taker storage (app/routers/agent.py): Aurora PostgreSQL rows, S3 files.
    aws_region: str = "eu-central-1"
    s3_bucket: str = ""
    # Aurora PostgreSQL (express configuration): IAM authentication only, no password.
    db_host: str = ""
    db_port: int = 5432
    db_name: str = "postgres"
    db_user: str = "postgres"

    # Langfuse Prompt Management (app/prompts.py). Empty keys: use the local prompts/*.md files.
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_base_url: str = "https://cloud.langfuse.com"
    # Trace agent runs that opt in (the lecture-notes agent). Traces hold the readings the
    # agent read, so turn this off when they must not leave the app.
    langfuse_tracing: bool = True


@lru_cache
def get_settings() -> Settings:
    return Settings()
