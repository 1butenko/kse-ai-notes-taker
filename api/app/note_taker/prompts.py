"""AI Note Taker system prompts, managed in Langfuse; see `app/prompts.py`."""

from app.prompts import get_prompt


def note_taker_prompt() -> str:
    return get_prompt("note-taker/orchestrator")


def moodle_prompt() -> str:
    return get_prompt("note-taker/moodle")
