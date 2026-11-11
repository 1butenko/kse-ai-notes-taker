"""System prompts, managed in Langfuse Prompt Management.

Each prompt is a Langfuse `text` prompt fetched by the `production` label. The Markdown file next to
the code that uses it is the fallback: it is used when Langfuse is not configured or unreachable,
and it is what `push` uploads. Variables use Langfuse `{{name}}` placeholders.

Langfuse is the source of truth: edit prompts in its UI. The Markdown files are a fallback kept in
sync with it, so commit them after a pull.

    uv run python -m app.prompts pull           # Langfuse production -> Markdown files
    uv run python -m app.prompts push           # create prompts Langfuse does not have yet
    uv run python -m app.prompts push --force   # overwrite Langfuse with the files

Agent skills (SKILL.md directories, see `app.note_taker.lecture_notes.skill_library`) are Langfuse
Skills and are pushed and pulled with the prompts.
"""

import sys
from functools import lru_cache
from pathlib import Path
from typing import Any

from langfuse import Langfuse
from langfuse.api import NotFoundError

from app.config import get_settings

LABEL = "production"
APP_DIR = Path(__file__).resolve().parent
LECTURE_NOTES = APP_DIR / "note_taker" / "lecture_notes" / "prompts"

# Langfuse prompt name -> fallback Markdown file.
PROMPTS: dict[str, Path] = {
    "note-taker/orchestrator": APP_DIR / "note_taker" / "prompts" / "orchestrator.md",
    "note-taker/moodle": APP_DIR / "note_taker" / "prompts" / "moodle.md",
    "note-taker/lecture-notes/writer": LECTURE_NOTES / "writer.md",
    "note-taker/lecture-notes/reviewer": LECTURE_NOTES / "reviewer.md",
    "note-taker/lecture-notes/skills-system": LECTURE_NOTES / "skills_system.md",
    "note-taker/lecture-notes/request": LECTURE_NOTES / "request.md",
}


@lru_cache
def langfuse_client() -> Langfuse | None:
    """The Langfuse client, or None when credentials are not set."""
    settings = get_settings()
    if not (settings.langfuse_public_key and settings.langfuse_secret_key):
        return None
    return Langfuse(
        public_key=settings.langfuse_public_key,
        secret_key=settings.langfuse_secret_key,
        base_url=settings.langfuse_base_url,
        # Agent runs that opt in are traced (app.note_taker.lecture_notes.tracing).
        tracing_enabled=settings.langfuse_tracing,
    )


def read_fallback(name: str) -> str:
    return PROMPTS[name].read_text(encoding="utf-8").strip()


def fill(text: str, variables: dict[str, object]) -> str:
    for key, value in variables.items():
        text = text.replace("{{" + key + "}}", str(value))
    return text


def get_prompt(name: str, **variables: object) -> str:
    """The `production` version of a prompt, with its variables filled in."""
    return get_prompt_ref(name, **variables)[0]


def get_prompt_ref(name: str, **variables: object) -> tuple[str, Any | None]:
    """The prompt's text and its Langfuse prompt, to link the generations that use it. The
    prompt is None when the local file was used (Langfuse off, unreachable, or the prompt
    missing), so a fallback is never linked."""
    fallback = read_fallback(name)
    client = langfuse_client()
    if client is None:
        return fill(fallback, variables), None
    prompt = client.get_prompt(name, label=LABEL, type="text", fallback=fallback)
    text = prompt.compile(**{key: str(value) for key, value in variables.items()})
    return text, None if getattr(prompt, "is_fallback", False) else prompt


def _production_text(client: Langfuse, name: str) -> tuple[str, int] | None:
    try:
        current = client.get_prompt(name, label=LABEL, type="text", cache_ttl_seconds=0)
    except NotFoundError:
        return None
    return current.prompt, current.version


def push(force: bool = False) -> None:
    """Create prompts that Langfuse does not have yet.

    Langfuse is the source of truth, so a prompt that already exists there and differs from the
    file is left alone (it was probably edited in the Langfuse UI): `pull` it, or use `--force` to
    overwrite it with the file.
    """
    client = langfuse_client()
    if client is None:
        sys.exit("Set LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY and LANGFUSE_BASE_URL first.")
    for name in PROMPTS:
        text = read_fallback(name)
        current = _production_text(client, name)
        if current is not None and current[0] == text:
            print(f"{name}: unchanged (version {current[1]})")
            continue
        if current is not None and not force:
            print(f"{name}: differs from Langfuse version {current[1]}; run pull or push --force")
            continue
        created = client.create_prompt(
            name=name,
            type="text",
            prompt=text,
            labels=[LABEL],
            commit_message=f"Upload {PROMPTS[name].relative_to(APP_DIR.parent).as_posix()}",
        )
        print(f"{name}: created version {created.version}")

    from app.note_taker.lecture_notes import skill_library as skills

    skills.push(client, force=force)


def pull() -> None:
    """Write the Langfuse `production` text of every prompt to its Markdown file."""
    client = langfuse_client()
    if client is None:
        sys.exit("Set LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY and LANGFUSE_BASE_URL first.")
    for name, path in PROMPTS.items():
        current = _production_text(client, name)
        if current is None:
            print(f"{name}: not in Langfuse yet; run push")
        elif current[0] == read_fallback(name):
            print(f"{name}: unchanged (version {current[1]})")
        else:
            path.write_text(current[0] + "\n", encoding="utf-8")
            print(f"{name}: updated {path.name} from version {current[1]}")

    from app.note_taker.lecture_notes import skill_library as skills

    skills.pull(client)


if __name__ == "__main__":
    args = sys.argv[1:]
    if args == ["pull"]:
        pull()
    elif args in (["push"], ["push", "--force"]):
        push(force="--force" in args)
    else:
        sys.exit("Usage: python -m app.prompts pull | push [--force]")
