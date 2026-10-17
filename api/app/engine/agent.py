from deepagents import create_deep_agent
from deepagents.backends import StateBackend
from langchain_core.language_models import BaseChatModel
from langchain_core.vectorstores import VectorStore

from app.engine.llm import build_chat_model
from app.engine.prompts import chunk_analyst_prompt, orchestrator_prompt, quarto_writer_prompt
from app.engine.tools import make_search_books_tool, write_quarto_document


def build_agent(vector_store: VectorStore, model: BaseChatModel | None = None):
    backend = StateBackend()
    search_books = make_search_books_tool(vector_store, backend)

    # Subagents still get the built-in filesystem tools (read_file etc.);
    # "tools" only sets the custom ones.
    chunk_analyst_subagent = {
        "name": "chunk-analyst",
        "description": (
            "Analyze one retrieved documentation chunk file. "
            "Pass the user question and a single file path under /retrieved/."
        ),
        "system_prompt": chunk_analyst_prompt(),
        "tools": [],
    }

    quarto_writer_subagent = {
        "name": "quarto-writer",
        "description": (
            "Write the final answer up as a Quarto (.qmd) study note and save it. "
            "Pass the user question, the final answer with its sources, "
            "and the /retrieved/ file paths used. "
            "Returns the path of the written .qmd file."
        ),
        "system_prompt": quarto_writer_prompt(),
        "tools": [write_quarto_document],
    }

    return create_deep_agent(
        model=model or build_chat_model(),
        tools=[search_books],
        backend=backend,
        system_prompt=orchestrator_prompt(),
        subagents=[chunk_analyst_subagent, quarto_writer_subagent],
    )
