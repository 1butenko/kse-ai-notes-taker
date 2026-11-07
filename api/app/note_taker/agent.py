"""The AI Note Taker main agent.

Built-ins: `write_todos` to plan the job (`TodoListMiddleware`; deepagents 0.7 no longer adds it by
default), the filesystem tools over a `StateBackend` (shared with subagents), and `task` to
delegate. The main agent has no tools of
its own: it reaches Moodle and, later, the note writers only through subagents.
"""

from deepagents import create_deep_agent
from deepagents.backends import StateBackend
from langchain.agents.middleware import TodoListMiddleware
from langchain_core.language_models import BaseChatModel
from langgraph.checkpoint.memory import MemorySaver

from app.config import get_settings
from app.note_taker.llm import build_chat_model
from app.note_taker.moodle.client import MoodleClient
from app.note_taker.moodle.store import MaterialsStore, PostgresMaterialsStore
from app.note_taker.moodle.tools import Upload
from app.note_taker.progress import Progress
from app.note_taker.project import Project
from app.note_taker.prompts import note_taker_prompt
from app.note_taker.subagents.moodle import build_moodle_subagent


def build_note_taker(
    course_id: str,
    moodle_course_id: int,
    *,
    model: BaseChatModel | None = None,
    approval: bool = False,
    moodle_client: MoodleClient | None = None,
    materials: MaterialsStore | None = None,
    upload: Upload | None = None,
    project: Project | None = None,
    progress: Progress | None = None,
):
    """Build the AI Note Taker for one course.

    `course_id` and `moodle_course_id` scope every subagent tool to this course; they are bound
    into the tools when the subagents are built, never passed by the LLM. `moodle_client`,
    `materials` and `upload` default to the real Moodle site, Postgres and S3; tests inject fakes.
    With a `project` (the app's course), the materials also go into the course and the lectures
    are prepared; `progress` receives every step for the course page.
    """
    backend = StateBackend()
    if moodle_client is None:
        settings = get_settings()
        moodle_client = MoodleClient(settings.moodle_url, settings.moodle_token)
    subagents = [
        build_moodle_subagent(
            moodle_client,
            materials or PostgresMaterialsStore(),
            backend,
            course_id,
            moodle_course_id,
            approval=approval,
            upload=upload,
            project=project,
            progress=progress,
        )
    ]

    return create_deep_agent(
        model=model or build_chat_model(),
        tools=[],
        system_prompt=note_taker_prompt(),
        backend=backend,
        subagents=subagents,
        middleware=[TodoListMiddleware()],
        # HITL interrupts need a checkpointer and a thread_id to pause and resume.
        checkpointer=MemorySaver() if approval else None,
        name="ai-note-taker",
    )
