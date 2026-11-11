"""The lecture-notes writer: a deep agent for one lecture.

Built-ins: `write_todos`, the filesystem tools over a `StateBackend` and `task`. Its own tool is
`render_notes`. Its subagent is the `reviewer`. Its skills (Quarto how-tos) are files under
`/skills/`, listed in its system prompt by a `SkillsMiddleware` whose template is a Langfuse
prompt. The lecture's brief and readings are files under `/lecture/` and `/readings/`, given to
`invoke` with the skills; the agent may not overwrite any of them.
"""

import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from deepagents import FilesystemPermission, create_deep_agent
from deepagents.backends import StateBackend
from deepagents.middleware.skills import SkillsMiddleware
from langchain.agents.middleware import AgentMiddleware, TodoListMiddleware
from langchain_core.language_models import BaseChatModel

from app.note_taker.lecture_notes import readings
from app.note_taker.lecture_notes.build import Runner, default_runner
from app.note_taker.lecture_notes.readings import LectureBundle
from app.note_taker.lecture_notes.reviewer import build_reviewer
from app.note_taker.lecture_notes.skill_library import (
    SKILLS_ROOT,
    Skill,
    load_skills,
)
from app.note_taker.lecture_notes.skill_library import (
    seed_files as skill_files,
)
from app.note_taker.lecture_notes.tools import RenderState, RunCancelled, make_render_tool
from app.note_taker.lecture_notes.tracing import link_prompt
from app.note_taker.progress import Progress
from app.prompts import get_prompt_ref

PROMPT = "note-taker/lecture-notes/"
PROTECTED = ["/skills/**", "/readings/**", "/lecture/**"]


class CancelCheck(AgentMiddleware):
    """Stops the run before the next model call once the lecture page asked to stop."""

    def __init__(self, cancelled: threading.Event | None) -> None:
        super().__init__()
        self.cancelled = cancelled

    def before_model(self, state: Any, runtime: Any) -> None:
        if self.cancelled is not None and self.cancelled.is_set():
            raise RunCancelled


@dataclass
class LectureNotesAgent:
    agent: Any
    runner: Runner
    files: dict[str, dict]  # the virtual filesystem to start with
    request: str  # the human message
    state: RenderState
    skills: list[Skill]
    prompt_versions: dict[str, int | None]  # None: the repo fallback was used


def build_lecture_notes_agent(
    bundle: LectureBundle,
    output: Path,
    *,
    model: BaseChatModel | None = None,
    reviewer_model: BaseChatModel | None = None,
    runner: Runner | None = None,
    progress: Progress | None = None,
    cancelled: threading.Event | None = None,
    max_renders: int = 12,
    skills: list[Skill] | None = None,
) -> LectureNotesAgent:
    """Build the writer for one lecture. The last good render is kept in `output`."""
    backend = StateBackend()
    writer, writer_ref = get_prompt_ref(PROMPT + "writer")
    reviewer, reviewer_ref = get_prompt_ref(PROMPT + "reviewer")
    skills_prompt, skills_ref = get_prompt_ref(PROMPT + "skills-system")
    request, request_ref = get_prompt_ref(
        PROMPT + "request",
        topic=bundle.topic,
        label=bundle.label,
        language="Ukrainian" if bundle.language == "uk" else "English",
    )
    skills = load_skills() if skills is None else skills
    state = RenderState()
    runner = runner or default_runner()
    render_notes = make_render_tool(
        backend,
        bundle,
        runner,
        output,
        state,
        max_renders=max_renders,
        progress=progress,
        cancelled=cancelled,
    )
    reviewer_spec = build_reviewer(reviewer, reviewer_ref)
    if reviewer_model is not None:
        reviewer_spec["model"] = reviewer_model
    if model is None:
        from app.note_taker.llm import build_chat_model

        model = build_chat_model()

    agent = create_deep_agent(
        model=model,
        tools=[render_notes],
        system_prompt=writer,
        backend=backend,
        subagents=[reviewer_spec],
        middleware=[
            TodoListMiddleware(),
            SkillsMiddleware(
                backend=backend, sources=[(SKILLS_ROOT, "Quarto")], system_prompt=skills_prompt
            ),
            CancelCheck(cancelled),
            *link_prompt(writer_ref),
        ],
        permissions=[FilesystemPermission(operations=["write"], paths=PROTECTED, mode="deny")],
        name="lecture-notes-writer",
    )
    versions = {
        PROMPT + name: getattr(ref, "version", None)
        for name, ref in (
            ("writer", writer_ref),
            ("reviewer", reviewer_ref),
            ("skills-system", skills_ref),
            ("request", request_ref),
        )
    }
    return LectureNotesAgent(
        agent=agent,
        runner=runner,
        files={**readings.seed_files(bundle), **skill_files(skills)},
        request=request,
        state=state,
        skills=skills,
        prompt_versions=versions,
    )
