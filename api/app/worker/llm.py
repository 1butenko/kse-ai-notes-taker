import base64
import json
from typing import Any

import httpx2
from fastapi import HTTPException, status
from langfuse import LangfuseGeneration, get_client
from pydantic import BaseModel, ValidationError

from app.worker.models import ModelSpec
from app.worker.openrouter import PARAMETERS, Completion, OpenRouterClient, OpenRouterError

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


def usage_details(usage: dict[str, Any]) -> dict[str, int]:
    prompt = usage.get("prompt_tokens") or 0
    completion = usage.get("completion_tokens") or 0
    cached = (usage.get("prompt_tokens_details") or {}).get("cached_tokens") or 0
    reasoning = (usage.get("completion_tokens_details") or {}).get("reasoning_tokens") or 0
    details = {"input": prompt - cached, "output": completion - reasoning}
    if cached:
        details["input_cached_tokens"] = cached
    if reasoning:
        details["output_reasoning_tokens"] = reasoning
    return details


def record(generation: LangfuseGeneration, completion: Completion) -> None:
    output: dict[str, Any] = {"role": "assistant", "content": completion.content}
    if completion.reasoning:
        output["reasoning"] = completion.reasoning
    cost = completion.usage.get("cost")
    generation.update(
        model=completion.model,
        output=output,
        usage_details=usage_details(completion.usage) if completion.usage else None,
        cost_details={"total": float(cost)} if isinstance(cost, int | float) else None,
    )


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
    with get_client().start_as_current_observation(
        as_type="generation",
        name=step,
        model=model_name,
        model_parameters={
            key: value if isinstance(value, str | int | float | bool) else json.dumps(value)
            for key, value in parameters.items()
        },
        input=messages,
        metadata={"response_schema": name, "plugins": plugins},
    ) as generation:
        try:
            completion = await client.complete_json(
                messages, name, strict_schema(model), plugins, model_name, parameters
            )
        except httpx2.TimeoutException as error:
            print(f"OpenRouter timed out ({name}): {error!r}")
            generation.update(level="ERROR", status_message=f"Timed out: {error!r}")
            raise HTTPException(status.HTTP_504_GATEWAY_TIMEOUT, "The model timed out") from error
        except (OpenRouterError, httpx2.HTTPError) as error:
            print(f"OpenRouter request failed ({name}): {error!r}")
            generation.update(level="ERROR", status_message=f"Request failed: {error!r}")
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, "The model request failed") from error

        record(generation, completion)
        try:
            return model.model_validate_json(completion.content)
        except ValidationError as error:
            print(f"Model returned an invalid {name}: {error}")
            generation.update(level="ERROR", status_message=f"Invalid {name}: {error}")
            raise HTTPException(
                status.HTTP_502_BAD_GATEWAY,
                f"The model returned an invalid {name.replace('_', ' ')}",
            ) from error
