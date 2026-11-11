"""The AI Note Taker for a course: its Moodle materials, fetched by the agent into S3 and
recorded in Aurora PostgreSQL.

The app's course is the uploads folder named by its Moodle course id (`/course-info/{course}`).
`POST /agent/courses/{course}/sync` links it to a `courses` row on first use, records a run and
has the worker execute it; `GET /agent/courses/{course}` is the materials panel's data, polled
while the run is going.
"""

import asyncio
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

import psycopg
from botocore.exceptions import BotoCoreError, ClientError
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, StringConstraints

from app import db, storage
from app.config import Settings, get_settings
from app.course import load_info
from app.note_taker import sync
from app.routers.plans import course_dir
from app.worker_client import WorkerClient, get_worker_client
from app.worker_contract import NoteTakerRequest

router = APIRouter(prefix="/agent/courses", tags=["agent"])

COURSE_COLUMNS = "c.id, c.title, c.s3_prefix, c.created_at, c.moodle_course_id, c.course_key"


class Material(BaseModel):
    id: UUID
    name: str
    mimetype: str
    size: int
    reason: str
    url: str


class Topic(BaseModel):
    section: int
    name: str
    summary: str
    materials: list[Material]


class Todo(BaseModel):
    content: str
    status: str  # pending | in_progress | completed


class AgentAction(BaseModel):
    text: str
    status: str  # running | done | failed
    detail: str = ""


class Run(BaseModel):
    id: UUID
    status: str
    focus: str | None
    # What the agent is doing right now, its todo list and its latest actions.
    step: str | None = None
    todos: list[Todo] = []
    actions: list[AgentAction] = []
    report: str | None
    error: str | None
    started_at: datetime
    finished_at: datetime | None


class AgentCourse(BaseModel):
    id: UUID
    course_key: str
    title: str
    s3_prefix: str
    created_at: datetime
    moodle_course_id: int
    materials: int
    topics: list[Topic]
    latest_run: Run | None


class SyncRequest(BaseModel):
    focus: Annotated[str | None, StringConstraints(strip_whitespace=True, max_length=500)] = None


@contextmanager
def storage_errors() -> Iterator[None]:
    """Missing or unreachable Postgres/S3/AWS credentials are a 503 with the reason."""
    try:
        yield
    except db.DatabaseNotConfigured as error:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(error)) from error
    except psycopg.OperationalError as error:
        print(f"Note Taker database unreachable: {error!r}")
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "The Note Taker database is unreachable"
        ) from error
    except (BotoCoreError, ClientError) as error:
        print(f"Note Taker AWS error: {error!r}")
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, f"AWS is unavailable: {error}"
        ) from error


def moodle_course_id(course: str) -> int:
    if not course.isdigit():
        raise HTTPException(
            status.HTTP_409_CONFLICT, "This course is not linked to a Moodle course"
        )
    return int(course)


def build_topics(
    topic_rows: list[dict[str, Any]],
    material_rows: list[dict[str, Any]],
    url_for: Callable[[str], str],
) -> list[dict[str, Any]]:
    """Group materials under their topic. A material whose section was never saved still shows."""
    topics: dict[int, dict[str, Any]] = {
        row["section"]: {
            "section": row["section"],
            "name": row["name"],
            "summary": row["summary"],
            "materials": [],
        }
        for row in topic_rows
    }
    for row in material_rows:
        topic = topics.setdefault(
            row["section"],
            {
                "section": row["section"],
                "name": row["section_name"],
                "summary": "",
                "materials": [],
            },
        )
        topic["materials"].append(
            {
                "id": row["id"],
                "name": row["name"],
                "mimetype": row["mimetype"],
                "size": row["size"],
                "reason": row["reason"],
                "url": url_for(row["s3_key"]),
            }
        )
    return [topics[section] for section in sorted(topics)]


def course_detail(
    course_key: str, url_for: Callable[[str], str] = storage.presigned_url
) -> dict[str, Any] | None:
    with db.transaction() as conn:
        course = conn.execute(
            f"SELECT {COURSE_COLUMNS} FROM courses c WHERE c.course_key = %s", (course_key,)
        ).fetchone()
        if course is None:
            return None
        topic_rows = conn.execute(
            "SELECT section, name, summary FROM course_topics WHERE course_id = %s",
            (course["id"],),
        ).fetchall()
        material_rows = conn.execute(
            "SELECT id, section, section_name, name, mimetype, size, s3_key, reason"
            " FROM materials WHERE course_id = %s ORDER BY section, name",
            (course["id"],),
        ).fetchall()
        run = conn.execute(
            f"SELECT {sync.RUN_COLUMNS} FROM sync_runs WHERE course_id = %s"
            " ORDER BY started_at DESC LIMIT 1",
            (course["id"],),
        ).fetchone()
    return {
        **course,
        "materials": len(material_rows),
        "topics": build_topics(topic_rows, material_rows, url_for),
        "latest_run": run,
    }


def ensure_course(conn: Any, course_key: str, title: str, moodle_id: int | None) -> dict[str, Any]:
    """The course's row, created on first use (with its S3 manifest), its title kept current."""
    course = conn.execute(
        "INSERT INTO courses (title, moodle_course_id, course_key) VALUES (%s, %s, %s)"
        " ON CONFLICT (course_key) DO UPDATE SET title = EXCLUDED.title,"
        " moodle_course_id = COALESCE(EXCLUDED.moodle_course_id, courses.moodle_course_id)"
        " RETURNING id, title, created_at, (xmax = 0) AS inserted",
        (title, moodle_id, course_key),
    ).fetchone()
    assert course is not None
    if course["inserted"]:
        # Rolls the row back if the S3 write fails.
        storage.write_manifest(course)
    return course


def begin_run(
    course_key: str, title: str, moodle_id: int, focus: str | None
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Link the course to its row and record a `running` run. The run is None when one is
    already live for this course."""
    with db.transaction() as conn:
        course = ensure_course(conn, course_key, title, moodle_id)
        return course, sync.start_run(conn, course["id"], focus)


@router.get("/{course}", response_model=AgentCourse)
def get_agent_course(course: str) -> dict[str, Any]:
    moodle_course_id(course)
    with storage_errors():
        detail = course_detail(course)
    if detail is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "The AI Note Taker has not run yet")
    return detail


@router.post("/{course}/sync", response_model=Run, status_code=status.HTTP_202_ACCEPTED)
async def post_sync(
    course: str,
    body: SyncRequest,
    settings: Annotated[Settings, Depends(get_settings)],
    worker: Annotated[WorkerClient, Depends(get_worker_client)],
) -> dict[str, Any]:
    """Have the AI Note Taker fetch the course's materials from Moodle; poll the GET."""
    moodle_id = moodle_course_id(course)
    info = load_info(course_dir(settings, course))
    if info is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Course not found")
    focus = body.focus or None
    with storage_errors():
        row, run = await asyncio.to_thread(begin_run, course, info.name, moodle_id, focus)
    if run is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "A run is already in progress")
    request = NoteTakerRequest(
        run_id=run["id"], course_id=row["id"], moodle_course_id=moodle_id, focus=focus
    )
    try:
        await worker.run_note_taker(request)
    except HTTPException as error:
        # The run never started: record why, so the panel shows it instead of spinning.
        await asyncio.to_thread(sync.finish_run, run["id"], error=f"Worker: {error.detail}")
        raise
    return run
