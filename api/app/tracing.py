from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from langfuse import Langfuse, LangfuseSpan, get_client, propagate_attributes

from app.config import Settings


def init_langfuse(settings: Settings) -> Langfuse:
    return Langfuse(
        public_key=settings.langfuse_public_key,
        secret_key=settings.langfuse_secret_key,
        base_url=settings.langfuse_base_url,
        environment=settings.environment,
        tracing_enabled=bool(settings.langfuse_public_key and settings.langfuse_secret_key),
    )


@contextmanager
def course_trace(name: str, course: str, input: Any) -> Iterator[LangfuseSpan]:
    with (
        get_client().start_as_current_observation(name=name, input=input) as span,
        propagate_attributes(session_id=f"course-{course}"),
    ):
        yield span
