"""The `motivation` subagent (the scout): decides on and drafts the hook that opens the note.

The writer calls it once before outlining. It reads the brief and the readings, decides whether
the lecture needs a hook at all (an introduction to the course or an organisational session does
not), picks one kind (a tangible problem, an application, a nerd-snipe or a historical moment),
and drafts it with one device that makes it new: a real image from the web, an animated SVG, or
a "try it first" interaction.

It has the web tools (`web.py`) the writer does not, so web text stays out of the writer's
context. It writes only `/notes/motivation.json` (its decision), `/notes/motivation.md` (the
draft) and `/notes/assets/*.svg`; the writer puts the draft at the top of the note.
"""

import json
from typing import Any

from deepagents import FilesystemPermission
from langchain_core.tools import BaseTool

from app.note_taker.lecture_notes.tracing import link_prompt

DECISION = "/notes/motivation.json"
DRAFT = "/notes/motivation.md"
KINDS = ("tangible-problem", "application", "nerd-snipe", "historical")
DEVICES = ("web-image", "animated-svg", "try-first", "none")

DESCRIPTION = (
    "Decides whether this lecture's note should open with a motivating hook and drafts it. It "
    "reads the brief and the readings, picks one kind of hook (tangible problem, application, "
    "nerd-snipe or historical moment), checks facts and finds a real image on the web when that "
    "helps, or draws an animated SVG or a 'try it first' interaction. It writes its decision to "
    "/notes/motivation.json and the draft to /notes/motivation.md. Call it once, before you "
    "outline the note."
)


def build_motivation(
    system_prompt: str,
    tools: list[BaseTool],
    prompt_ref: Any | None = None,
    protected: list[str] | None = None,
) -> dict:
    return {
        "name": "motivation",
        "description": DESCRIPTION,
        "system_prompt": system_prompt,
        "tools": tools,
        "permissions": [
            FilesystemPermission(
                operations=["write"],
                paths=["/notes/index.qmd", "/notes/sign-off.txt", *(protected or [])],
                mode="deny",
            )
        ],
        "middleware": link_prompt(prompt_ref),
    }


def read_decision(text: str | None) -> dict[str, Any] | None:
    """The scout's decision, kept on the run's row: only known keys, bounded. None when it
    wrote none or not JSON."""
    if not text:
        return None
    try:
        raw = json.loads(text)
    except ValueError:
        return None
    if not isinstance(raw, dict):
        return None
    decision: dict[str, Any] = {"needed": bool(raw.get("needed"))}
    for key, allowed in (("kind", KINDS), ("device", DEVICES)):
        if raw.get(key) in allowed:
            decision[key] = raw[key]
    if isinstance(raw.get("reason"), str):
        decision["reason"] = raw["reason"][:1000]
    if isinstance(raw.get("candidates"), list):
        decision["candidates"] = [str(c)[:300] for c in raw["candidates"][:5]]
    if isinstance(raw.get("sources"), list):
        decision["sources"] = [
            {"url": str(s.get("url", ""))[:500], "title": str(s.get("title", ""))[:200]}
            for s in raw["sources"][:10]
            if isinstance(s, dict) and str(s.get("url", "")).startswith("https://")
        ]
    return decision
