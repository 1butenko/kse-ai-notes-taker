from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass, field
from typing import Annotated, Any

import httpx2
from fastapi import Depends

from app.worker.config import WorkerSettings, get_worker_settings

PARAMETERS = {"temperature": 0, "max_tokens": 16000}
LONG_TIMEOUT = 600


class OpenRouterError(Exception):
    pass


@dataclass
class Completion:
    content: str
    model: str
    usage: dict[str, Any] = field(default_factory=dict)
    reasoning: str | None = None


class OpenRouterClient:
    def __init__(self, base_url: str, api_key: str, model: str, http: httpx2.AsyncClient) -> None:
        self.endpoint = f"{base_url.rstrip('/')}/chat/completions"
        self.api_key = api_key
        self.model = model
        self.http = http

    async def complete_json(
        self,
        messages: list[dict[str, Any]],
        schema_name: str,
        schema: dict[str, Any],
        plugins: list[dict[str, Any]] | None = None,
        model: str | None = None,
        parameters: dict[str, Any] | None = None,
    ) -> Completion:
        body: dict[str, Any] = {
            "model": model or self.model,
            "messages": messages,
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": schema_name, "strict": True, "schema": schema},
            },
            "provider": {"require_parameters": True},
            **(parameters or PARAMETERS),
        }
        if plugins:
            body["plugins"] = plugins

        response = await self.http.post(
            self.endpoint, json=body, headers={"Authorization": f"Bearer {self.api_key}"}
        )
        try:
            payload = response.json()
        except ValueError:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        if response.is_error or "error" in payload:
            error = payload.get("error") or {}
            if isinstance(error, dict):
                error = error.get("message", response.reason_phrase)
            raise OpenRouterError(f"{response.status_code}: {error}")

        try:
            message = payload["choices"][0]["message"]
            content = message["content"]
        except (KeyError, IndexError, TypeError) as error:
            raise OpenRouterError("Response has no message content") from error
        if not isinstance(content, str) or not content:
            raise OpenRouterError("Response has no message content")
        usage = payload.get("usage")
        reasoning = message.get("reasoning")
        return Completion(
            content=content,
            model=payload.get("model") or model or self.model,
            usage=usage if isinstance(usage, dict) else {},
            reasoning=reasoning if isinstance(reasoning, str) and reasoning else None,
        )


async def get_openrouter_client(
    settings: Annotated[WorkerSettings, Depends(get_worker_settings)],
) -> AsyncIterator[OpenRouterClient | None]:
    if not settings.openrouter_api_key:
        yield None
        return
    async with openrouter_opener(settings, 120)() as client:
        yield client


type Opener = Callable[[], AbstractAsyncContextManager[OpenRouterClient]]


def openrouter_opener(settings: WorkerSettings, timeout: float) -> Opener:
    @asynccontextmanager
    async def open_client() -> AsyncIterator[OpenRouterClient]:
        async with httpx2.AsyncClient(timeout=timeout) as http:
            yield OpenRouterClient(
                settings.openrouter_url,
                settings.openrouter_api_key or "",
                settings.openrouter_model,
                http,
            )

    return open_client


def get_openrouter_opener(
    settings: Annotated[WorkerSettings, Depends(get_worker_settings)],
) -> Opener | None:
    """Opens clients for background jobs, which outlive the request's own client."""
    if not settings.openrouter_api_key:
        return None
    return openrouter_opener(settings, LONG_TIMEOUT)
