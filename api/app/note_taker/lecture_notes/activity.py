"""What the lecture page shows as a run's current step, between the tools' own actions.

Without this, the step was updated only by `write_todos`, hand-offs and renders, and the long
stretches of reading and writing in between showed the first step ("Reading the lecture") again.
This callback sees every tool call, the subagents' too: deepagents passes the run's callbacks
into them and tags each call with `lc_agent_name`.
"""

import re
from typing import Any

from langchain_core.callbacks import BaseCallbackHandler

from app.note_taker.progress import Progress

WRITER = "lecture-notes-writer"
SUBAGENTS = {"motivation": "Finding a hook for the opening", "reviewer": "Reviewing the notes"}
PREFIX = {"motivation": "Hook: ", "reviewer": "Review: "}


def reading_name(path: str) -> str:
    """`/readings/02-linear-systems.md` -> `linear systems`."""
    stem = path.rsplit("/", 1)[-1].removesuffix(".md")
    return re.sub(r"^\d+-", "", stem).replace("-", " ") or stem


def describe(name: str, inputs: dict[str, Any]) -> str | None:
    """A short step for a tool call, or None for calls not worth showing."""
    path = str(inputs.get("file_path") or inputs.get("path") or "")
    if name == "read_file":
        if path.startswith("/readings/"):
            return f"Reading {reading_name(path)}"
        if path.startswith("/skills/"):
            return f"Reading the {path.split('/')[2]} skill"
        if path == "/lecture/brief.md":
            return "Reading the lecture brief"
        if path.startswith("/notes/"):
            return "Re-reading the notes"
    if name in ("grep", "glob"):
        return "Searching the readings"
    if name in ("write_file", "edit_file"):
        if path == "/notes/motivation.md":
            return "Drafting the hook"
        if path.startswith("/notes/assets/"):
            return "Drawing a figure"
        if path == "/notes/index.qmd":
            return "Writing the notes" if name == "write_file" else "Revising the notes"
    return None


class NotesActivity(BaseCallbackHandler):
    """Keeps `progress` on what the writer and its subagents are doing."""

    def __init__(self, progress: Progress) -> None:
        self.progress = progress

    def on_tool_start(
        self,
        serialized: dict[str, Any],
        input_str: str,
        *,
        inputs: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        name = (serialized or {}).get("name", "")
        inputs = inputs or {}
        agent = (metadata or {}).get("lc_agent_name") or WRITER
        if name == "write_todos":
            # Only the writer's list is the run's plan; a subagent's would replace it.
            if agent == WRITER and isinstance(inputs.get("todos"), list):
                self.progress.set_todos(inputs["todos"])
            return
        if name == "task":
            subagent = str(inputs.get("subagent_type") or "a subagent")
            self.progress.note(f"Handing the work to the {subagent} agent")
            self.progress.set_activity(SUBAGENTS.get(subagent, f"The {subagent} agent is working"))
            return
        if step := describe(name, inputs):
            self.progress.set_activity(PREFIX.get(agent, "") + step)

    def on_tool_end(self, output: Any, *, name: str | None = None, **kwargs: Any) -> None:
        if name == "task":  # back with the writer, whose next call sets the step again
            self.progress.set_activity("Working on the notes")
