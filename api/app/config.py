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


@lru_cache
def get_settings() -> Settings:
    return Settings()
