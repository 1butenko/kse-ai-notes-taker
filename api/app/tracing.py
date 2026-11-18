"""Langfuse tracing for every model call: who made it, in which session, and what it cost.

All model calls run in the worker. Each request it serves is one trace, with:

- `user_id`: the signed-in teacher (`users.id`) who started it, or the service (`worker`, `web`)
  when no teacher did. The API passes it in the worker request (`worker_contract.Traced`).
- `session_id`: the course (`course-<key>`), so everything done for one course (syllabus,
  mapping, page transcription, AI Note Taker runs, lecture notes) shows together.
- Per generation: the model OpenRouter served, token usage (input, cached input, output,
  reasoning) and the cost OpenRouter reports, so Langfuse needs no price table for these models.

Attached files (syllabi, book pages) are never sent: a generation's input keeps only their names
(`without_files`). This has to happen before Langfuse sees the input, since its SDK uploads
base64 files as media before any `mask` runs.

Direct OpenRouter calls (`app.worker.llm.ask`) record their generation with `record_completion`;
LangChain agents pass `callback_handler()` in their callbacks, which adds OpenRouter's cost to
what Langfuse's own handler records.

Without Langfuse keys, or with `LANGFUSE_TRACING=false`, nothing is traced.
"""

import json
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from app import prompts
from app.config import get_settings

ANONYMOUS = "worker"


def tracing_on() -> bool:
    return prompts.langfuse_client() is not None and get_settings().langfuse_tracing


def course_session(course: str) -> str:
    """The Langfuse session of everything done for one course."""
    return f"course-{course}"


@contextmanager
def traced(
    name: str,
    *,
    user_id: str | None,
    session_id: str,
    input: Any = None,
    metadata: dict[str, str] | None = None,
    tags: list[str] | None = None,
    as_type: str = "span",
    **attributes: Any,
) -> Iterator[Any]:
    """One trace: a root observation (yielded; None when tracing is off) whose user, session,
    name, tags and metadata propagate to every observation below it. `attributes` go to
    `propagate_attributes` too (such as `skills_available`)."""
    client = prompts.langfuse_client()
    if client is None or not get_settings().langfuse_tracing:
        yield None
        return

    from langfuse import propagate_attributes

    with (
        client.start_as_current_observation(name=name, as_type=as_type, input=input) as root,
        propagate_attributes(
            user_id=user_id or ANONYMOUS,
            session_id=session_id,
            trace_name=name,
            tags=tags,
            metadata=metadata,
            **attributes,
        ),
    ):
        yield root


def without_files(messages: Any) -> Any:
    """`messages` with each attached file (an OpenRouter `file` part) reduced to its name."""
    if isinstance(messages, list):
        return [without_files(item) for item in messages]
    if isinstance(messages, dict):
        if messages.get("type") == "file" and isinstance(messages.get("file"), dict):
            name = messages["file"].get("filename") or "file"
            return {"type": "file", "file": {"filename": name, "file_data": "(not traced)"}}
        return {key: without_files(value) for key, value in messages.items()}
    return messages


@contextmanager
def generation(
    name: str, *, model: str, input: Any, parameters: dict[str, Any], metadata: dict[str, Any]
) -> Iterator[Any]:
    """A generation observation under the current trace (None when tracing is off). Attached
    files in `input` are reduced to their names."""
    client = prompts.langfuse_client()
    if client is None or not get_settings().langfuse_tracing:
        yield None
        return
    with client.start_as_current_observation(
        name=name,
        as_type="generation",
        model=model,
        # Langfuse takes scalar parameters only.
        model_parameters={
            key: value if isinstance(value, str | int | float | bool) else json.dumps(value)
            for key, value in parameters.items()
        },
        input=without_files(input),
        metadata=metadata,
    ) as observation:
        yield observation


def flush() -> None:
    """Send what is buffered now; for long background runs, so their trace shows when they end."""
    client = prompts.langfuse_client()
    if client is None:
        return
    try:
        client.flush()
    except Exception as error:
        print(f"Could not flush the Langfuse trace: {error!r}")


def usage_details(usage: dict[str, Any]) -> dict[str, int]:
    """OpenRouter's (OpenAI-style) usage as Langfuse usage types. Cached input and reasoning
    output are their own types, so `input` and `output` are what remains."""
    prompt = int(usage.get("prompt_tokens") or 0)
    completion = int(usage.get("completion_tokens") or 0)
    cached = int((usage.get("prompt_tokens_details") or {}).get("cached_tokens") or 0)
    reasoning = int((usage.get("completion_tokens_details") or {}).get("reasoning_tokens") or 0)
    details = {"input": max(0, prompt - cached), "output": max(0, completion - reasoning)}
    if cached:
        details["input_cached_tokens"] = cached
    if reasoning:
        details["output_reasoning_tokens"] = reasoning
    return details


def cost_details(cost: Any) -> dict[str, float] | None:
    """OpenRouter's reported cost (USD) as Langfuse cost, which then wins over model prices."""
    if isinstance(cost, bool) or not isinstance(cost, int | float):
        return None
    return {"total": float(cost)}


def record_completion(
    generation: Any, model: str, content: str, usage: dict[str, Any], reasoning: str | None
) -> None:
    """Record an OpenRouter answer on its generation (None when tracing is off)."""
    if generation is None:
        return
    output: dict[str, Any] = {"role": "assistant", "content": content}
    if reasoning:
        output["reasoning"] = reasoning
    generation.update(
        model=model,
        output=output,
        usage_details=usage_details(usage) if usage else None,
        cost_details=cost_details(usage.get("cost")),
    )


def openrouter_cost(response: Any) -> float | None:
    """The cost `ChatOpenRouter` puts in an answer's `response_metadata`, if any."""
    total = 0.0
    found = False
    for generations in getattr(response, "generations", None) or []:
        for generation in generations:
            metadata = getattr(getattr(generation, "message", None), "response_metadata", None)
            cost = cost_details((metadata or {}).get("cost"))
            if cost is not None:
                total += cost["total"]
                found = True
    return total if found else None


def callback_handler() -> Any:
    """Langfuse's LangChain handler, plus OpenRouter's cost on each generation. Langfuse's
    handler records the tokens and model but not the provider's cost, and its price table
    doesn't know OpenRouter's model names, so without this LangChain calls would cost 0."""
    from langfuse.langchain import CallbackHandler

    class OpenRouterCallbackHandler(CallbackHandler):
        def on_llm_end(self, response: Any, *, run_id: Any, **kwargs: Any) -> Any:
            cost = openrouter_cost(response)
            # The handler ends (and forgets) the generation in on_llm_end: add the cost first.
            generation = self._runs.get(run_id)
            if cost is not None and generation is not None:
                try:
                    generation.update(cost_details={"total": cost})
                except Exception as error:
                    print(f"Could not record the model cost in Langfuse: {error!r}")
            return super().on_llm_end(response, run_id=run_id, **kwargs)

    return OpenRouterCallbackHandler(public_key=get_settings().langfuse_public_key)
