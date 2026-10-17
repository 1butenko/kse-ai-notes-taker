"""Offline stand-ins for every external service the engine needs.

API calls are disabled for now. Each factory below is the single place to wire the real service:

- `build_chat_model`: chat model (was `ChatOpenRouter(model="openai/gpt-5.5")`)
- `build_embeddings`: embeddings (was OpenRouter `voyageai/voyage-4`, 1024 dimensions)
- `vectorstore.build_vector_store`: vector database (was Amazon S3 Vectors)
"""

from collections.abc import Iterator

from langchain_core.embeddings import DeterministicFakeEmbedding, Embeddings
from langchain_core.language_models import BaseChatModel
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage

from app.engine.config import EMBEDDING_DIMENSION

OFFLINE_REPLY = "LLM calls are disabled in this build; the generation engine is running offline."


def _offline_replies() -> Iterator[AIMessage]:
    while True:
        yield AIMessage(content=OFFLINE_REPLY)


class OfflineChatModel(GenericFakeChatModel):
    """Answers every request with OFFLINE_REPLY and never calls tools."""

    def bind_tools(self, tools, **kwargs) -> "OfflineChatModel":
        return self


def build_chat_model() -> BaseChatModel:
    return OfflineChatModel(messages=_offline_replies())


def build_embeddings() -> Embeddings:
    # Deterministic hash-based vectors: the same text always gets the same vector, no network.
    return DeterministicFakeEmbedding(size=EMBEDDING_DIMENSION)
