"""The `moodle` subagent: gathers the course materials, stores them in S3 and in the app's
course, reads the syllabus into lectures and attaches the readings to them."""

from deepagents.backends import StateBackend

from app.note_taker.moodle.client import MoodleClient
from app.note_taker.moodle.store import MaterialsStore
from app.note_taker.moodle.tools import Upload, make_moodle_tools
from app.note_taker.progress import Progress
from app.note_taker.project import Project
from app.note_taker.prompts import moodle_prompt

DESCRIPTION = (
    "Prepares the course from its Moodle site. Lists the course, chooses what is relevant for "
    "note-taking (the syllabus, slides, readings, pages, link readings; not forums, quizzes or "
    "assignments), downloads it into the course, reads the syllabus into lectures, matches the "
    "cited books and attaches the readings to their lectures. Writes /materials/manifest.json "
    "and /course/lectures.json. Give it one complete instruction: the focus topic, if any, and "
    "the rules for what to keep or skip."
)


def build_moodle_subagent(
    client: MoodleClient,
    store: MaterialsStore,
    backend: StateBackend,
    course_id: str,
    moodle_course_id: int,
    *,
    approval: bool = False,
    upload: Upload | None = None,
    project: Project | None = None,
    progress: Progress | None = None,
) -> dict:
    tools = make_moodle_tools(
        client,
        backend,
        store,
        course_id,
        moodle_course_id,
        **({"upload": upload} if upload else {}),
        project=project,
        progress=progress,
    )
    return {
        "name": "moodle",
        "description": DESCRIPTION,
        "system_prompt": moodle_prompt(),
        "tools": tools,
        # A human sees the chosen items and reasons, and can approve, edit or reject the download.
        **({"interrupt_on": {"fetch_materials": True}} if approval else {}),
    }
