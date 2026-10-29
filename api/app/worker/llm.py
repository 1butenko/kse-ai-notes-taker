import base64
from typing import Any

import httpx2
from fastapi import HTTPException, status
from pydantic import BaseModel, ValidationError

from app.worker.models import ModelSpec
from app.worker.openrouter import PARAMETERS, OpenRouterClient, OpenRouterError

PDF_PLUGINS = [{"id": "file-parser", "pdf": {"engine": "native"}}]


def strict_schema(model: type[BaseModel]) -> dict[str, Any]:
    """JSON schema with $refs inlined, since not every provider resolves them."""
    schema = model.model_json_schema()
    defs = schema.pop("$defs", {})

    def inline(node: Any) -> Any:
        if isinstance(node, dict):
            if "$ref" in node:
                return inline(defs[node["$ref"].rsplit("/", 1)[-1]])
            return {key: inline(value) for key, value in node.items()}
        if isinstance(node, list):
            return [inline(item) for item in node]
        return node

    return inline(schema)


def pdf_part(filename: str, data: bytes) -> dict[str, Any]:
    encoded = base64.b64encode(data).decode()
    return {
        "type": "file",
        "file": {"filename": filename, "file_data": f"data:application/pdf;base64,{encoded}"},
    }


def chat(system: str, *parts: dict[str, Any] | str) -> list[dict[str, Any]]:
    content = [{"type": "text", "text": p} if isinstance(p, str) else p for p in parts]
    return [{"role": "system", "content": system}, {"role": "user", "content": content}]


async def ask[T: BaseModel](
    client: OpenRouterClient,
    messages: list[dict[str, Any]],
    model: type[T],
    name: str,
    plugins: list[dict[str, Any]] | None = None,
    *,
    step: str,
    spec: ModelSpec | None = None,
) -> T:
    """Ask for a `model`-shaped answer, mapping failures to 502/504."""
    model_name = spec.model if spec else client.model
    parameters = spec.parameters() if spec else PARAMETERS
    try:
        completion = await client.complete_json(
            messages, name, strict_schema(model), plugins, model_name, parameters
        )
    except httpx2.TimeoutException as error:
        print(f"OpenRouter timed out ({name}): {error!r}")
        raise HTTPException(status.HTTP_504_GATEWAY_TIMEOUT, "The model timed out") from error
    except (OpenRouterError, httpx2.HTTPError) as error:
        print(f"OpenRouter request failed ({name}): {error!r}")
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "The model request failed") from error

    try:
        return model.model_validate_json(completion.content)
    except ValidationError as error:
        print(f"Model returned an invalid {name}: {error}")
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            f"The model returned an invalid {name.replace('_', ' ')}",
        ) from error
