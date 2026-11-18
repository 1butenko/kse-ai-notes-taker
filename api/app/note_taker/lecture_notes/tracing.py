"""Langfuse tracing for lecture-notes runs.

One trace per run: a root `agent` observation, with every model call and tool call below it via
Langfuse's LangChain callback handler (deepagents passes the run's callbacks into subagents, so
the reviewer is traced too). The trace carries the course, lecture and run, the skills the agent
had (with their Langfuse versions), and each generation links to the Langfuse prompt version that
produced it (`LinkPrompt`). User, session and cost are recorded as for every trace (`app.tracing`).

Without Langfuse keys, or with `LANGFUSE_TRACING=false`, nothing is traced.
"""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

from langchain.agents.middleware import AgentMiddleware

from app import tracing
from app.tracing import tracing_on


class LinkPrompt(AgentMiddleware):
    """Links the generations of the agent it is on to a Langfuse prompt version."""

    def __init__(self, prompt: Any) -> None:
        super().__init__()
        self.prompt = prompt

    def wrap_model_call(self, request: Any, handler: Callable[[Any], Any]) -> Any:
        from langfuse import propagate_attributes

        with propagate_attributes(prompt=self.prompt):
            return handler(request)

    async def awrap_model_call(self, request: Any, handler: Callable[[Any], Any]) -> Any:
        from langfuse import propagate_attributes

        with propagate_attributes(prompt=self.prompt):
            return await handler(request)


def link_prompt(prompt: Any | None) -> list[AgentMiddleware]:
    """`LinkPrompt` for a Langfuse prompt; nothing for a fallback (None)."""
    return [LinkPrompt(prompt)] if prompt is not None and tracing_on() else []


@dataclass
class Trace:
    callbacks: list[Any] = field(default_factory=list)
    trace_id: str | None = None
    root: Any = None

    def finish(self, output: str) -> None:
        if self.root is not None:
            self.root.update(output=output)


@contextmanager
def traced_run(
    name: str,
    *,
    user_id: str | None,
    session_id: str,
    input: str,
    metadata: dict[str, str],
    tags: list[str],
    skills: list[dict],
) -> Iterator[Trace]:
    try:
        with tracing.traced(
            name,
            user_id=user_id,
            session_id=session_id,
            input=input,
            metadata=metadata,
            tags=tags,
            as_type="agent",
            skills_available=skills,
        ) as root:
            if root is None:
                yield Trace()
            else:
                yield Trace(
                    callbacks=[tracing.callback_handler()], trace_id=root.trace_id, root=root
                )
    finally:
        tracing.flush()
