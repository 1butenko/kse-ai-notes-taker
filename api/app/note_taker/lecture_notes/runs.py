"""Runs of the lecture-notes agent, recorded in `lecture_note_runs`.

The API records a run and the worker executes it (`execute_run`, in a thread). The lecture page
polls the row for the agent's todo list, actions and current step. When the agent is done, the
last build that rendered is uploaded to S3 and its file list saved on the row; the API serves the
page from there. Runs are not durable: a worker restart marks running rows failed.
"""

import shutil
import threading
from collections.abc import Callable
from datetime import timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

from psycopg.types.json import Jsonb

from app import db, storage
from app.note_taker.progress import Progress

STALE_AFTER = timedelta(minutes=45)
FIRST_STEP = "Reading the lecture"
RUN_COLUMNS = (
    "id, course_id, session_id, session_label, status, step, todos, actions, report, error,"
    " s3_prefix, files, readings_fingerprint, model, prompt_versions, langfuse_trace_id, renders,"
    " started_at, finished_at"
)

# Set by POST /lecture-notes/runs/{id}/cancel; checked before every model call and render.
CANCEL: dict[UUID, threading.Event] = {}


def start_run(
    conn: Any, course_id: UUID, session_id: str, label: str, fingerprint: str
) -> dict[str, Any] | None:
    """Create a `running` row, or return None when this lecture already has a live run."""
    live = conn.execute(
        "SELECT 1 FROM lecture_note_runs WHERE course_id = %s AND session_id = %s"
        " AND status = 'running' AND started_at > now() - %s",
        (course_id, session_id, STALE_AFTER),
    ).fetchone()
    if live:
        return None
    return conn.execute(
        "INSERT INTO lecture_note_runs"
        " (course_id, session_id, session_label, step, readings_fingerprint)"
        f" VALUES (%s, %s, %s, %s, %s) RETURNING {RUN_COLUMNS}",
        (course_id, session_id, label, FIRST_STEP, fingerprint),
    ).fetchone()


def save_progress(
    run_id: UUID, todos: list[dict[str, Any]], actions: list[dict[str, Any]], step: str | None
) -> None:
    with db.transaction() as conn:
        conn.execute(
            "UPDATE lecture_note_runs SET todos = %s, actions = %s, step = %s"
            " WHERE id = %s AND status = 'running'",
            (Jsonb(todos), Jsonb(actions), step or FIRST_STEP, run_id),
        )


def finish_run(
    run_id: UUID,
    status: str,
    *,
    report: str | None = None,
    error: str | None = None,
    **fields: Any,
) -> None:
    """Record the outcome. `fields`: s3_prefix, files, model, prompt_versions, langfuse_trace_id,
    renders."""
    columns = {"status": status, "report": report, "error": error}
    for key, value in fields.items():
        columns[key] = Jsonb(value) if key in ("files", "prompt_versions") else value
    assignments = ", ".join(f"{key} = %s" for key in columns)
    with db.transaction() as conn:
        conn.execute(
            f"UPDATE lecture_note_runs SET {assignments}, finished_at = now()"
            " WHERE id = %s AND status = 'running'",
            (*columns.values(), run_id),
        )


def fail_interrupted_runs() -> int:
    """Only this worker executes runs: any still `running` when it starts were cut off."""
    with db.transaction() as conn:
        cursor = conn.execute(
            "UPDATE lecture_note_runs SET status = 'failed', finished_at = now(),"
            " error = 'Interrupted: the worker restarted. Create the notes again.'"
            " WHERE status = 'running'"
        )
        return cursor.rowcount


def publish(build: Path, prefix: str) -> list[str]:
    """Upload a rendered site under `prefix`; returns its files, relative to it."""
    files = sorted(p.relative_to(build).as_posix() for p in build.rglob("*") if p.is_file())
    for name in files:
        storage.put_file(prefix + name, build / name)
    return files


def execute_run(
    run_id: UUID,
    course_id: UUID,
    course: str,
    session_id: str,
    *,
    model: Any = None,
    runner: Any = None,
    skills: list | None = None,
    publisher: Callable[[Path, str], list[str]] = publish,
) -> None:
    """Write, render and publish one lecture's notes. Never raises: the outcome is on the row.

    `model`, `runner`, `skills` and `publisher` default to OpenRouter, Quarto, the Langfuse skills
    and S3; tests pass fakes."""
    # Imported here so the worker starts without building the agent's dependencies.
    from langchain_core.messages import HumanMessage

    from app.note_taker.lecture_notes.agent import build_lecture_notes_agent
    from app.note_taker.lecture_notes.readings import load_lecture
    from app.note_taker.lecture_notes.skill_library import references
    from app.note_taker.lecture_notes.tools import RunCancelled, digest, note_from_files, render
    from app.note_taker.lecture_notes.tracing import traced_run
    from app.note_taker.llm import build_chat_model
    from app.note_taker.sync import MainAgentProgress
    from app.worker.config import get_worker_settings

    settings = get_worker_settings()
    cancelled = CANCEL.setdefault(run_id, threading.Event())
    progress = Progress(
        save=lambda todos, actions, step: save_progress(run_id, todos, actions, step)
    )
    workdir = settings.uploads_dir / ".lecture-notes" / str(run_id)
    output = workdir / "build"
    model_name = settings.lecture_notes_model or settings.note_taker_model
    record: dict[str, Any] = {"model": model_name}
    try:
        with progress.action("Reading the lecture's readings") as action:
            bundle = load_lecture(
                settings.uploads_dir, course, session_id, settings.lecture_notes_max_chars
            )
            if not bundle.readings:
                raise ValueError("None of this lecture's readings has text the agent can read")
            action.detail = f"{len(bundle.readings)} reading(s)"
        built = build_lecture_notes_agent(
            bundle,
            output,
            model=model or build_chat_model(model_name),
            reviewer_model=(
                build_chat_model(settings.lecture_notes_reviewer_model)
                if settings.lecture_notes_reviewer_model and model is None
                else None
            ),
            runner=runner,
            progress=progress,
            cancelled=cancelled,
            max_renders=settings.lecture_notes_max_renders,
            skills=skills,
        )
        skills = references(built.skills)
        record["prompt_versions"] = {
            "prompts": built.prompt_versions,
            "skills": {s["name"]: s.get("version") for s in skills},
        }
        with traced_run(
            "lecture-notes",
            session_id=f"course-{course}",
            input=built.request,
            metadata={"course": course, "session": session_id, "run": str(run_id)},
            tags=["lecture-notes"],
            skills=skills,
        ) as trace:
            record["langfuse_trace_id"] = trace.trace_id
            result = built.agent.invoke(
                {"messages": [HumanMessage(content=built.request)], "files": built.files},
                config={
                    "callbacks": [*trace.callbacks, MainAgentProgress(progress)],
                    "recursion_limit": 300,
                },
            )
            report = result["messages"][-1].text
            trace.finish(report)

        state = built.state
        body, assets = note_from_files(result.get("files", {}))
        if body and digest(body, assets) != state.good_digest:
            # The agent edited after its last good render: render the final version once more.
            # A failure leaves the last good build in place.
            with progress.action("Rendering the final version") as action:
                final, message = render(bundle, body, assets, built.runner, output)
                if final is not None:
                    state.good = final
                else:
                    action.status = "failed"
                    action.detail = " ".join(message.splitlines()[:4])[:400]
                    if state.good is not None:
                        report += (
                            "\n\nThe last edits did not render; the published page is the last "
                            "version that did."
                        )
        if state.good is None:
            raise ValueError("The notes never rendered. The agent said: " + report[:500])
        with progress.action("Publishing the page") as action:
            prefix = storage.lecture_notes_prefix(course_id, session_id, run_id)
            files = publisher(output, prefix)
            action.detail = f"{len(files)} files"
        finish_run(
            run_id,
            "succeeded",
            report=report,
            s3_prefix=prefix,
            files=files,
            renders=state.renders,
            **record,
        )
    except RunCancelled:
        finish_run(run_id, "cancelled", error="Stopped from the lecture page", **record)
    except Exception as error:
        finish_run(run_id, "failed", error=f"{type(error).__name__}: {error}", **record)
    finally:
        CANCEL.pop(run_id, None)
        shutil.rmtree(workdir, ignore_errors=True)
