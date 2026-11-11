"""Visual lecture notes: the lecture-notes agent's runs for one lecture, and their pages.

`POST /lecture-notes/{course}/{session}/runs` records a run and has the worker execute it; the
lecture page polls the run. A finished run's page is served from S3 under
`/lecture-notes/runs/{run}/site/`, for a sandboxed iframe. The page is model-written, so it is
served with a CSP that keeps it in an opaque origin and only lets it load its own files and the
CDN that MathJax and Observable JS come from.
"""

import asyncio
from datetime import datetime
from typing import Annotated, Any
from urllib.parse import quote
from uuid import UUID

from botocore.exceptions import ClientError
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app import db, storage
from app.config import Settings, get_settings
from app.course import load_info
from app.note_taker.lecture_notes import runs
from app.plan import UnknownSession, aligned, scope_to_session, session_fingerprint
from app.routers.agent import AgentAction, Todo, ensure_course, storage_errors
from app.routers.plans import SESSION_ID, course_dir
from app.worker_client import WorkerClient, get_worker_client
from app.worker_contract import LectureNotesRequest

router = APIRouter(prefix="/lecture-notes", tags=["lecture-notes"])

CDN = "https://cdn.jsdelivr.net/npm/"


class LectureNotesRun(BaseModel):
    id: UUID
    session_id: str
    session_label: str
    status: str  # running | succeeded | failed | cancelled
    step: str | None = None
    todos: list[Todo] = []
    actions: list[AgentAction] = []
    report: str | None
    error: str | None
    files: list[str] = []
    model: str | None = None
    prompt_versions: dict[str, Any] = {}
    langfuse_trace_id: str | None = None
    renders: int = 0
    # The lecture's readings changed since this run read them.
    readings_changed: bool = False
    started_at: datetime
    finished_at: datetime | None


def lecture(settings: Settings, course: str, session_id: str) -> tuple[str, str, int, str]:
    """The course title, the lecture's label, how many files it has and their fingerprint.
    404 for an unknown course or lecture."""
    info = load_info(course_dir(settings, course))
    if info is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Course not found")
    if not SESSION_ID.match(session_id):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid lecture")
    plan, transcript, _ = aligned(settings.uploads_dir, course)
    if transcript is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "This course has no lectures yet")
    try:
        scoped, scoped_transcript = scope_to_session(plan, transcript, session_id)
    except UnknownSession as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Lecture not found") from error
    session = scoped_transcript.sessions[0]
    label = f"{session.label}: {session.topic}" if session.topic else session.label
    return info.name, label, len(scoped.sessions[0].files), session_fingerprint(plan, session_id)


def with_changes(row: dict[str, Any], fingerprint: str | None) -> dict[str, Any]:
    return {
        **row,
        "readings_changed": bool(
            fingerprint
            and row["readings_fingerprint"]
            and row["readings_fingerprint"] != fingerprint
        ),
    }


def get_run(run_id: UUID) -> dict[str, Any] | None:
    with db.transaction() as conn:
        return conn.execute(
            f"SELECT {runs.RUN_COLUMNS} FROM lecture_note_runs WHERE id = %s", (run_id,)
        ).fetchone()


def begin(course: str, title: str, session_id: str, label: str, fingerprint: str):
    with db.transaction() as conn:
        row = ensure_course(conn, course, title, int(course) if course.isdigit() else None)
        return row, runs.start_run(conn, row["id"], session_id, label, fingerprint)


@router.post(
    "/{course}/{session_id}/runs",
    response_model=LectureNotesRun,
    status_code=status.HTTP_202_ACCEPTED,
)
async def start_lecture_notes(
    course: str,
    session_id: str,
    settings: Annotated[Settings, Depends(get_settings)],
    worker: Annotated[WorkerClient, Depends(get_worker_client)],
) -> dict[str, Any]:
    """Have the lecture-notes agent write this lecture's visual notes; poll the run."""
    title, label, files, fingerprint = await asyncio.to_thread(
        lecture, settings, course, session_id
    )
    if not files:
        raise HTTPException(status.HTTP_409_CONFLICT, "Add readings to this lecture first")
    with storage_errors():
        row, run = await asyncio.to_thread(begin, course, title, session_id, label, fingerprint)
    if run is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Notes for this lecture are being written")
    request = LectureNotesRequest(
        run_id=run["id"], course_id=row["id"], course=course, session_id=session_id
    )
    try:
        await worker.run_lecture_notes(request)
    except HTTPException as error:
        # The run never started: record why, so the page shows it instead of spinning.
        await asyncio.to_thread(
            runs.finish_run, run["id"], "failed", error=f"Worker: {error.detail}"
        )
        raise
    return with_changes(run, fingerprint)


@router.get("/{course}/{session_id}/runs", response_model=list[LectureNotesRun])
def list_lecture_notes(
    course: str, session_id: str, settings: Annotated[Settings, Depends(get_settings)]
) -> list[dict[str, Any]]:
    """The lecture's runs, newest first. Empty when the course was never linked."""
    _, _, _, fingerprint = lecture(settings, course, session_id)
    with storage_errors():
        rows = list_runs(course, session_id)
    return [with_changes(row, fingerprint) for row in rows]


def list_runs(course: str, session_id: str) -> list[dict[str, Any]]:
    columns = ", ".join("r." + c.strip() for c in runs.RUN_COLUMNS.split(","))
    with db.transaction() as conn:
        return conn.execute(
            f"SELECT {columns} FROM lecture_note_runs r JOIN courses c ON c.id = r.course_id"
            " WHERE c.course_key = %s AND r.session_id = %s ORDER BY r.started_at DESC LIMIT 20",
            (course, session_id),
        ).fetchall()


class LectureNotesStatus(BaseModel):
    """One lecture's notes: its latest run, and the latest that published a page (the same run
    when that one succeeded)."""

    session_id: str
    latest: LectureNotesRun
    published: LectureNotesRun | None


def course_fingerprints(settings: Settings, course: str) -> dict[str, str]:
    if load_info(course_dir(settings, course)) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Course not found")
    plan, _, _ = aligned(settings.uploads_dir, course)
    return {s.id: session_fingerprint(plan, s.id) for s in plan.sessions}


def latest_runs(course: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Each lecture's latest run, and its latest succeeded run."""
    columns = ", ".join("r." + c.strip() for c in runs.RUN_COLUMNS.split(","))
    query = (
        f"SELECT DISTINCT ON (r.session_id) {columns} FROM lecture_note_runs r"
        " JOIN courses c ON c.id = r.course_id WHERE c.course_key = %s{}"
        " ORDER BY r.session_id, r.started_at DESC"
    )
    with db.transaction() as conn:
        latest = conn.execute(query.format(""), (course,)).fetchall()
        published = conn.execute(query.format(" AND r.status = 'succeeded'"), (course,)).fetchall()
    return latest, published


@router.get("/{course}/runs", response_model=list[LectureNotesStatus])
def course_lecture_notes(
    course: str, settings: Annotated[Settings, Depends(get_settings)]
) -> list[dict[str, Any]]:
    """Every lecture's notes, for the lecture list. Lectures without a run are left out."""
    fingerprints = course_fingerprints(settings, course)
    with storage_errors():
        latest, published = latest_runs(course)
    done = {row["session_id"]: row for row in published}
    return [
        {
            "session_id": row["session_id"],
            "latest": with_changes(row, fingerprints.get(row["session_id"])),
            "published": (
                with_changes(done[row["session_id"]], fingerprints.get(row["session_id"]))
                if row["session_id"] in done
                else None
            ),
        }
        for row in latest
    ]


@router.get("/runs/{run_id}", response_model=LectureNotesRun)
def get_lecture_notes(run_id: UUID) -> dict[str, Any]:
    with storage_errors():
        row = get_run(run_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Run not found")
    return with_changes(row, None)


@router.post("/runs/{run_id}/cancel", response_model=LectureNotesRun)
async def cancel_lecture_notes(
    run_id: UUID, worker: Annotated[WorkerClient, Depends(get_worker_client)]
) -> dict[str, Any]:
    """Stop a run. One the worker no longer has (lost in a restart) is marked cancelled here."""
    with storage_errors():
        row = await asyncio.to_thread(get_run, run_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Run not found")
    if row["status"] == "running":
        reply = await worker.cancel_lecture_notes(run_id)
        if not reply.cancelled:
            await asyncio.to_thread(
                runs.finish_run, run_id, "cancelled", error="Stopped from the lecture page"
            )
    with storage_errors():
        row = await asyncio.to_thread(get_run, run_id)
    assert row is not None
    return with_changes(row, None)


def site_policy(base: str) -> str:
    return (
        "sandbox allow-scripts allow-popups allow-popups-to-escape-sandbox; default-src 'none'; "
        # Observable JS compiles its cells in the browser, which needs eval; the page has an
        # opaque origin, so it reaches no cookies or storage of the app.
        f"script-src 'unsafe-inline' 'unsafe-eval' {base} {CDN}; "
        f"style-src 'unsafe-inline' {base} {CDN}; "
        f"img-src data: blob: {base}; font-src data: {base} {CDN}; "
        f"connect-src {base} {CDN}; worker-src blob:; "
        "base-uri 'none'; form-action 'none'; object-src 'none'; frame-src 'none'"
    )


@router.get("/runs/{run_id}/site/{path:path}")
def lecture_notes_site(
    run_id: UUID, path: str, settings: Annotated[Settings, Depends(get_settings)]
) -> StreamingResponse:
    """One file of a published page: only the files the run published."""
    with storage_errors():
        row = get_run(run_id)
    path = path or "index.html"
    if row is None or row["status"] != "succeeded" or path not in (row["files"] or []):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    with storage_errors():
        try:
            obj = storage.get_object(row["s3_prefix"] + path)
        except ClientError as error:
            if error.response.get("Error", {}).get("Code") in ("NoSuchKey", "404"):
                raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found") from error
            raise
    base = f"{settings.public_api_url}/lecture-notes/runs/{quote(str(run_id))}/site/"
    headers = {
        "Access-Control-Allow-Origin": "*",
        "X-Book-Published": "1",
        "X-Content-Type-Options": "nosniff",
        "Referrer-Policy": "no-referrer",
        "Cache-Control": "private, max-age=31536000, immutable",
    }
    media = obj.get("ContentType") or "application/octet-stream"
    if path.endswith(".html"):
        headers["Content-Security-Policy"] = site_policy(base)
    if path.endswith(".qmd"):
        media = "text/markdown; charset=utf-8"
        headers["Content-Disposition"] = 'attachment; filename="lecture-notes.qmd"'
    return StreamingResponse(obj["Body"].iter_chunks(), media_type=media, headers=headers)
