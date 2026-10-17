"""System prompts, stored as Markdown files in `prompts/`.

Variables use Langfuse-style `{{name}}` placeholders so the files can move back to Langfuse later.
"""

from app.engine.config import MAX_CONCURRENT_ANALYSTS, PROMPTS_DIR


def load_prompt(name: str, **variables: object) -> str:
    text = (PROMPTS_DIR / f"{name}.md").read_text(encoding="utf-8").strip()
    for key, value in variables.items():
        text = text.replace("{{" + key + "}}", str(value))
    return text


def orchestrator_prompt() -> str:
    return load_prompt("orchestrator", max_concurrent_analysts=MAX_CONCURRENT_ANALYSTS)


def chunk_analyst_prompt() -> str:
    return load_prompt("chunk_analyst")


def quarto_writer_prompt() -> str:
    return load_prompt("quarto_writer")
