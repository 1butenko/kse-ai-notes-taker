"""The `reviewer` subagent: checks the writer's note against the readings and reports problems.

It has only the built-in file tools, and may not write: a permission rule denies every write, so
it can read the note, the brief and the readings but never change them.
"""

from typing import Any

from deepagents import FilesystemPermission

from app.note_taker.lecture_notes.tracing import link_prompt

DESCRIPTION = (
    "Reviews the lecture note at /notes/index.qmd against the brief and the readings: "
    "faithfulness and math, coverage of the syllabus subtopics, clarity, the visuals (it re-reads "
    "every Mermaid diagram) and engagement. Returns a numbered list of issues, most serious first. "
    "It never edits. Call it once after the note renders cleanly."
)


def build_reviewer(system_prompt: str, prompt_ref: Any | None = None) -> dict:
    return {
        "name": "reviewer",
        "description": DESCRIPTION,
        "system_prompt": system_prompt,
        "tools": [],
        "permissions": [FilesystemPermission(operations=["write"], paths=["/**"], mode="deny")],
        "middleware": link_prompt(prompt_ref),
    }
