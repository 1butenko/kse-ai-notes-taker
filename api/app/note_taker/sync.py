"""Runs the AI Note Taker for a course and records the run in `sync_runs`.

The API starts a run and the worker executes it; the course page polls its progress (`todos`,
`actions`, `step`). Runs are not durable: if the worker restarts mid-run, the row stays `running`
until `STALE_AFTER` passes.
"""

import re
from datetime import timedelta
from typing import Any
from urllib.parse import parse_qs, urlparse
from uuid import UUID

from langchain_core.callbacks import BaseCallbackHandler
from psycopg.types.json import Jsonb

from app import db
from app.note_taker.progress import Progress

STALE_AFTER = timedelta(minutes=30)
RUN_COLUMNS = (
    "id, course_id, focus, status, step, todos, actions, report, error, started_at, finished_at"
)
FIRST_STEP = "Starting the AI Note Taker"


def parse_moodle_course_id(value: object) -> int | None:
    """A Moodle course id from a number or a link such as `.../course/view.php?id=42`."""
    if value is None or value == "":
        return None
    if isinstance(value, int):
        return value
    text = str(value).strip()
    if re.fullmatch(r"\d+", text):
        return int(text)
    ids = parse_qs(urlparse(text).query).get("id", [])
    if len(ids) == 1 and ids[0].isdigit():
        return int(ids[0])
    raise ValueError(
        "Enter a Moodle course id or a link like https://moodle.example/course/view.php?id=42"
    )


def request_message(course_id: UUID, moodle_course_id: int, focus: str | None) -> str:
    message = (
        f"Prepare course {course_id} (Moodle {moodle_course_id}): gather its materials, read its "
        "syllabus into lectures and attach the readings to them"
    )
    return f"{message}, focus: {focus}" if focus else message


def start_run(conn: Any, course_id: UUID, focus: str | None) -> dict[str, Any] | None:
    """Create a `running` row, or return None when this course already has a live run."""
    live = conn.execute(
        "SELECT 1 FROM sync_runs WHERE course_id = %s AND status = 'running'"
        " AND started_at > now() - %s",
        (course_id, STALE_AFTER),
    ).fetchone()
    if live:
        return None
    return conn.execute(
        "INSERT INTO sync_runs (course_id, focus, step) VALUES (%s, %s, %s)"
        f" RETURNING {RUN_COLUMNS}",
        (course_id, focus, FIRST_STEP),
    ).fetchone()


def save_progress(
    run_id: UUID, todos: list[dict[str, Any]], actions: list[dict[str, Any]], step: str | None
) -> None:
    with db.transaction() as conn:
        conn.execute(
            "UPDATE sync_runs SET todos = %s, actions = %s, step = %s"
            " WHERE id = %s AND status = 'running'",
            (Jsonb(todos), Jsonb(actions), step or FIRST_STEP, run_id),
        )


def fail_interrupted_runs() -> int:
    """Runs only this worker executes: any still `running` when it starts were cut off."""
    with db.transaction() as conn:
        cursor = conn.execute(
            "UPDATE sync_runs SET status = 'failed', finished_at = now(),"
            " error = 'Interrupted: the worker restarted. Run the AI Note Taker again.'"
            " WHERE status = 'running'"
        )
        return cursor.rowcount


def finish_run(run_id: UUID, *, report: str | None = None, error: str | None = None) -> None:
    with db.transaction() as conn:
        conn.execute(
            "UPDATE sync_runs SET status = %s, report = %s, error = %s, finished_at = now()"
            " WHERE id = %s",
            ("failed" if error else "succeeded", report, error, run_id),
        )


class MainAgentProgress(BaseCallbackHandler):
    """The main agent's own calls: its todo list and the hand-offs to subagents. (Subagent tools
    report themselves; callbacks do not reach them.)"""

    def __init__(self, progress: Progress) -> None:
        self.progress = progress

    def on_tool_start(
        self,
        serialized: dict[str, Any],
        input_str: str,
        *,
        inputs: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        name = (serialized or {}).get("name", "")
        inputs = inputs or {}
        if name == "write_todos" and isinstance(inputs.get("todos"), list):
            self.progress.set_todos(inputs["todos"])
        elif name == "task":
            subagent = inputs.get("subagent_type") or "a subagent"
            self.progress.note(f"Handing the work to the {subagent} agent")


def execute_run(run_id: UUID, course_id: UUID, moodle_course_id: int, focus: str | None) -> None:
    """Run the orchestrator to the end. Never raises: a failure is stored on the run."""
    progress = Progress(
        save=lambda todos, actions, step: save_progress(run_id, todos, actions, step)
    )
    try:
        # Imported here so importing the API does not build a chat model.
        from langchain_core.messages import HumanMessage

        from app.note_taker.agent import build_note_taker
        from app.note_taker.project import Project

        agent = build_note_taker(
            str(course_id),
            moodle_course_id,
            # The app's course key is its Moodle course id.
            project=Project.connect(str(moodle_course_id)),
            progress=progress,
        )
        result = agent.invoke(
            {
                "messages": [
                    HumanMessage(content=request_message(course_id, moodle_course_id, focus))
                ]
            },
            config={"callbacks": [MainAgentProgress(progress)]},
        )
        finish_run(run_id, report=result["messages"][-1].text)
    except Exception as error:
        finish_run(run_id, error=f"{type(error).__name__}: {error}")
