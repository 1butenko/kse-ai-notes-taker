"""Langfuse tracing: every trace has a user and a session, and every generation its model, token
usage and OpenRouter's cost.

Spans go to an in-memory OpenTelemetry exporter through a real Langfuse client, so the tests
check the attributes Langfuse receives without a Langfuse server.
"""

import asyncio
import json
from collections.abc import Iterator
from typing import Any

import httpx2
import pytest
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langfuse import Langfuse
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from pydantic import BaseModel

from app import prompts, tracing
from app.config import Settings
from app.worker.llm import ask
from app.worker.openrouter import OpenRouterClient

PUBLIC_KEY = "pk-lf-tracing-test"
EXPORTER = InMemorySpanExporter()
USAGE = {
    "prompt_tokens": 1200,
    "completion_tokens": 300,
    "total_tokens": 1500,
    "prompt_tokens_details": {"cached_tokens": 200},
    "completion_tokens_details": {"reasoning_tokens": 100},
    "cost": 0.0042,
}


@pytest.fixture
def spans(monkeypatch: pytest.MonkeyPatch) -> Iterator[InMemorySpanExporter]:
    client = Langfuse(
        public_key=PUBLIC_KEY,
        secret_key="sk-lf-tracing-test",
        base_url="http://langfuse.test",
        tracer_provider=TracerProvider(),
        span_exporter=EXPORTER,
        flush_at=1,
    )
    settings = Settings(
        langfuse_public_key=PUBLIC_KEY, langfuse_secret_key="sk", langfuse_tracing=True
    )
    monkeypatch.setattr(prompts, "langfuse_client", lambda: client)
    monkeypatch.setattr(tracing, "get_settings", lambda: settings)
    EXPORTER.clear()
    yield EXPORTER
    client.flush()


def finished(exporter: InMemorySpanExporter) -> dict[str, dict[str, Any]]:
    prompts.langfuse_client().flush()
    return {span.name: dict(span.attributes or {}) for span in exporter.get_finished_spans()}


def details(attributes: dict[str, Any], key: str) -> dict[str, Any]:
    return json.loads(attributes[f"langfuse.observation.{key}"])


class Answer(BaseModel):
    text: str


def openrouter(usage: dict[str, Any]) -> OpenRouterClient:
    def reply(_: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            200,
            json={
                "model": "openai/gpt-test-served",
                "choices": [{"message": {"content": '{"text": "hi"}'}}],
                "usage": usage,
            },
        )

    http = httpx2.AsyncClient(transport=httpx2.MockTransport(reply))
    return OpenRouterClient("http://openrouter.test", "key", "openai/gpt-test", http)


def test_ask_records_user_session_usage_and_cost(spans: InMemorySpanExporter) -> None:
    async def run() -> None:
        with tracing.traced(
            "transcribe-syllabus", user_id="teacher-1", session_id=tracing.course_session("42")
        ):
            await ask(openrouter(USAGE), [], Answer, "answer", step="extract-reading-plan")

    asyncio.run(run())
    by_name = finished(spans)

    root, generation = by_name["transcribe-syllabus"], by_name["extract-reading-plan"]
    for span in (root, generation):
        assert span["user.id"] == "teacher-1"
        assert span["session.id"] == "course-42"
    assert generation["langfuse.observation.type"] == "generation"
    assert generation["langfuse.observation.model.name"] == "openai/gpt-test-served"
    assert details(generation, "usage_details") == {
        "input": 1000,
        "input_cached_tokens": 200,
        "output": 200,
        "output_reasoning_tokens": 100,
    }
    assert details(generation, "cost_details") == {"total": 0.0042}


def test_a_trace_without_a_teacher_is_the_worker(spans: InMemorySpanExporter) -> None:
    with tracing.traced("map-materials", user_id=None, session_id="course-7"):
        pass
    assert finished(spans)["map-materials"]["user.id"] == "worker"


class OpenRouterLike(BaseChatModel):
    """Answers like `ChatOpenRouter`: usage in `usage_metadata`, cost in `response_metadata`."""

    @property
    def _llm_type(self) -> str:
        return "openrouter-like"

    def _generate(self, messages: Any, stop: Any = None, run_manager: Any = None, **_: Any):
        message = AIMessage(
            content="done",
            response_metadata={"model_name": "anthropic/claude-test", "cost": 0.0125},
            usage_metadata={"input_tokens": 900, "output_tokens": 100, "total_tokens": 1000},
        )
        return ChatResult(generations=[ChatGeneration(message=message)])


def test_langchain_generations_get_openrouter_cost(spans: InMemorySpanExporter) -> None:
    with tracing.traced("prepare-course", user_id="teacher-2", session_id="course-9") as root:
        assert root is not None
        OpenRouterLike().invoke(
            [HumanMessage(content="go")], config={"callbacks": [tracing.callback_handler()]}
        )

    finished(spans)
    generations = [
        dict(s.attributes or {})
        for s in spans.get_finished_spans()
        if (s.attributes or {}).get("langfuse.observation.type") == "generation"
    ]
    assert len(generations) == 1
    generation = generations[0]
    assert generation["user.id"] == "teacher-2"
    assert generation["session.id"] == "course-9"
    assert details(generation, "usage_details") == {"input": 900, "output": 100, "total": 1000}
    assert details(generation, "cost_details") == {"total": 0.0125}


def test_usage_details_without_cached_or_reasoning_tokens() -> None:
    assert tracing.usage_details({"prompt_tokens": 10, "completion_tokens": 5}) == {
        "input": 10,
        "output": 5,
    }
    assert tracing.cost_details(None) is None and tracing.cost_details(True) is None


def test_nothing_is_traced_without_langfuse() -> None:
    with tracing.traced("x", user_id="u", session_id="s") as root:
        assert root is None
    with tracing.generation("g", model="m", input=[], parameters={}, metadata={}) as generation:
        assert generation is None


def test_attached_pdfs_are_not_sent_to_langfuse(spans: InMemorySpanExporter) -> None:
    from app.worker.llm import chat, pdf_part

    messages = chat("Read it.", "Page 3.", pdf_part("book-p3.pdf", b"%PDF-1.4 book text"))

    async def run() -> None:
        with tracing.traced("transcribe-pages", user_id="teacher-1", session_id="course-42"):
            await ask(openrouter(USAGE), messages, Answer, "answer", step="transcribe-page")

    asyncio.run(run())
    traced_input = finished(spans)["transcribe-page"]["langfuse.observation.input"]

    assert "base64" not in traced_input and "@@@langfuseMedia" not in traced_input
    assert "book-p3.pdf" in traced_input and "Page 3." in traced_input
    # The model itself still gets the PDF.
    assert messages[1]["content"][1]["file"]["file_data"].startswith("data:application/pdf;base64,")
