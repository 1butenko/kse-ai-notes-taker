from langchain_core.language_models import BaseChatModel
from langchain_openrouter import ChatOpenRouter

from app.worker.config import get_worker_settings


def build_chat_model(model: str | None = None) -> BaseChatModel:
    """The agent's chat model (`note_taker_model` unless named). Built only in the worker, which
    owns OpenRouter."""
    settings = get_worker_settings()
    return ChatOpenRouter(
        model=model or settings.note_taker_model,
        api_key=settings.openrouter_api_key or None,
    )
