from pathlib import Path

from langchain_core.documents import Document
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, HumanMessage

from app.engine.agent import build_agent
from app.engine.llm import OFFLINE_REPLY
from app.engine.prompts import chunk_analyst_prompt, orchestrator_prompt, quarto_writer_prompt
from app.engine.tools import write_quarto_document
from app.engine.vectorstore import build_vector_store

BOOK_CHUNKS = [
    Document(
        page_content="An eigenvalue of A is a scalar such that Av = lambda v.",
        metadata={"source": "strang.pdf"},
    ),
    Document(
        page_content="A basis is a linearly independent spanning set.",
        metadata={"source": "axler.pdf"},
    ),
]


class ScriptedModel(GenericFakeChatModel):
    def bind_tools(self, tools, **kwargs) -> "ScriptedModel":
        return self


def test_prompts_have_no_unfilled_variables() -> None:
    for prompt in (orchestrator_prompt(), chunk_analyst_prompt(), quarto_writer_prompt()):
        assert prompt and "{{" not in prompt
    assert "Launch up to 3 parallel task() calls" in orchestrator_prompt()


def test_write_quarto_document_header_and_body(qmd_output_dir: Path) -> None:
    body = "$v \\neq 0$ and $$\\begin{bmatrix}2 & 0\\\\ 0 & 3\\end{bmatrix}$$"
    write_quarto_document.invoke(
        {
            "filename": "../Eigen values!",
            "title": "Eigenvalues: a 'quick' note",
            "body": body,
            "toc_depth": 2,
        }
    )
    text = (qmd_output_dir / "Eigen-values.qmd").read_text(encoding="utf-8")
    assert text.startswith(
        "---\ntitle: 'Eigenvalues: a ''quick'' note'\nformat:\n  html:\n    toc: true\n"
    )
    assert "toc-depth: 2" in text and "html-math-method: katex" in text and "css:" not in text
    assert text.endswith(body + "\n")


def test_offline_model_answers_without_api_calls() -> None:
    agent = build_agent(build_vector_store(BOOK_CHUNKS))
    result = agent.invoke({"messages": [HumanMessage(content="What is an eigenvalue?")]})
    assert result["messages"][-1].text == OFFLINE_REPLY


def test_agent_searches_then_quarto_writer_saves_note(qmd_output_dir: Path) -> None:
    note = {
        "filename": "eigenvalues",
        "title": "Eigenvalues",
        "body": "## Definition\n\n$Av = \\lambda v$",
    }
    model = ScriptedModel(
        messages=iter(
            [
                AIMessage(
                    content="",
                    tool_calls=[
                        {"name": "search_books", "args": {"query": "eigenvalue"}, "id": "1"}
                    ],
                ),
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "task",
                            "args": {
                                "subagent_type": "quarto-writer",
                                "description": "Write up: Av = lambda v",
                            },
                            "id": "2",
                        }
                    ],
                ),
                AIMessage(
                    content="",
                    tool_calls=[{"name": "write_quarto_document", "args": note, "id": "3"}],
                ),
                AIMessage(content="Saved the note."),
                AIMessage(content="Answer ready, note saved."),
            ]
        )
    )
    result = build_agent(build_vector_store(BOOK_CHUNKS), model=model).invoke(
        {"messages": [HumanMessage(content="Define eigenvalues")]}
    )

    assert result["messages"][-1].text == "Answer ready, note saved."
    assert any(path.startswith("/retrieved/") for path in result["files"])
    assert (
        (qmd_output_dir / "eigenvalues.qmd")
        .read_text(encoding="utf-8")
        .endswith("$Av = \\lambda v$\n")
    )
