import asyncio
import fcntl
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated
from uuid import UUID

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, status

from app.syllabus import SyllabusExtraction
from app.worker import vision
from app.worker.config import WorkerSettings, get_worker_settings
from app.worker.llm import ask
from app.worker.mapping import run_mapping
from app.worker.openrouter import (
    Opener,
    OpenRouterClient,
    get_openrouter_client,
    get_openrouter_opener,
)
from app.worker.transcribe import EmptyDocument, build_messages, drop_bad_refs
from app.worker_contract import (
    BooksRequest,
    BooksResponse,
    LectureNotesCancel,
    LectureNotesCancelResponse,
    LectureNotesRequest,
    LectureNotesResponse,
    MapRequest,
    MapResponse,
    NoteTakerRequest,
    NoteTakerResponse,
    TranscribeRequest,
    TranscribeResponse,
)

COURSE = re.compile(r"^(local|\d+)$")

settings = get_worker_settings()


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    settings.uploads_dir.mkdir(parents=True, exist_ok=True)
    with (settings.uploads_dir / ".worker.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise RuntimeError(
                "Another worker is already serving this uploads directory"
            ) from error
        try:
            await asyncio.to_thread(fail_interrupted_note_taker_runs)
            await asyncio.to_thread(fail_interrupted_lecture_note_runs)
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def fail_interrupted_note_taker_runs() -> None:
    """Without its database (not configured, or AWS logged out) the worker still starts."""
    try:
        from app.note_taker import sync

        if count := sync.fail_interrupted_runs():
            print(f"Marked {count} interrupted AI Note Taker run(s) as failed")
    except Exception as error:
        print(f"Could not check for interrupted AI Note Taker runs: {error!r}")


def fail_interrupted_lecture_note_runs() -> None:
    try:
        from app.note_taker.lecture_notes import runs

        if count := runs.fail_interrupted_runs():
            print(f"Marked {count} interrupted lecture-notes run(s) as failed")
    except Exception as error:
        print(f"Could not check for interrupted lecture-notes runs: {error!r}")


app = FastAPI(title="kse-ai-notes-taker-worker", lifespan=lifespan)


def upload(settings: WorkerSettings, path: str) -> Path:
    root = settings.uploads_dir.resolve()
    file = (root / path).resolve()
    if not file.is_relative_to(root):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Path is outside the uploads directory")
    if not file.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File not found")
    return file


@app.post("/transcribe")
async def transcribe(
    body: TranscribeRequest,
    settings: Annotated[WorkerSettings, Depends(get_worker_settings)],
    client: Annotated[OpenRouterClient | None, Depends(get_openrouter_client)],
) -> TranscribeResponse:
    if client is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Transcription is not configured")

    file = upload(settings, body.path)
    try:
        messages, plugins = build_messages(file)
    except EmptyDocument as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error)) from error

    extraction = await ask(
        client, messages, SyllabusExtraction, "transcript", plugins, step="extract-reading-plan"
    )
    drop_bad_refs(extraction)

    return TranscribeResponse(extraction=extraction, model=client.model)


@app.post("/map")
async def map_materials(
    body: MapRequest,
    settings: Annotated[WorkerSettings, Depends(get_worker_settings)],
    client: Annotated[OpenRouterClient | None, Depends(get_openrouter_client)],
) -> MapResponse:
    if not COURSE.match(body.course):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Invalid course: {body.course!r}")
    if client is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Mapping is not configured")

    directory = settings.uploads_dir / body.course
    matches, proposals = await run_mapping(
        client, settings.uploads_dir, directory, body.plan, body.transcript, body.books
    )
    return MapResponse(matches=matches, proposals=proposals)


@app.post("/books/transcribe", status_code=status.HTTP_202_ACCEPTED)
async def transcribe_books(
    body: BooksRequest,
    background: BackgroundTasks,
    settings: Annotated[WorkerSettings, Depends(get_worker_settings)],
    opener: Annotated[Opener | None, Depends(get_openrouter_opener)],
) -> BooksResponse:
    """Transcribe, in the background, the pages of the course's approved excerpts that their
    PDF text garbles (see `vision`)."""
    if not COURSE.match(body.course):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Invalid course: {body.course!r}")
    spec = vision.vision_spec(settings)
    if opener is None or spec is None:
        return BooksResponse(started=False)
    background.add_task(vision.keep_transcribing, opener, spec, settings.uploads_dir, body.course)
    return BooksResponse(started=True)


@app.post("/note-taker/runs", status_code=status.HTTP_202_ACCEPTED)
async def run_note_taker(
    body: NoteTakerRequest,
    background: BackgroundTasks,
    settings: Annotated[WorkerSettings, Depends(get_worker_settings)],
) -> NoteTakerResponse:
    """Run the AI Note Taker for a course in the background. The run's outcome is written to its
    `sync_runs` row (see `app.note_taker.sync`), which the API reads."""
    if not settings.openrouter_api_key:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "OPENROUTER_API_KEY is not set on the worker"
        )
    # Imported here so the worker starts without building the agent's dependencies.
    from app.note_taker import sync

    # A sync function: Starlette runs it in a thread, off the event loop.
    background.add_task(
        sync.execute_run, body.run_id, body.course_id, body.moodle_course_id, body.focus
    )
    return NoteTakerResponse(started=True)


# Lecture-notes runs going on this worker; at most `lecture_notes_concurrency` at once.
LECTURE_NOTES: set[UUID] = set()


@app.post("/lecture-notes/runs", status_code=status.HTTP_202_ACCEPTED)
async def run_lecture_notes(
    body: LectureNotesRequest,
    background: BackgroundTasks,
    settings: Annotated[WorkerSettings, Depends(get_worker_settings)],
) -> LectureNotesResponse:
    """Write one lecture's notes in the background. The outcome is written to its
    `lecture_note_runs` row (see `app.note_taker.lecture_notes.runs`), which the API reads."""
    if not COURSE.match(body.course):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Invalid course: {body.course!r}")
    if not settings.openrouter_api_key:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "OPENROUTER_API_KEY is not set on the worker"
        )
    if len(LECTURE_NOTES) >= max(1, settings.lecture_notes_concurrency):
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "Other lectures' notes are being written; try again in a few minutes",
        )
    from app.note_taker.lecture_notes import runs

    LECTURE_NOTES.add(body.run_id)

    def execute() -> None:
        try:
            runs.execute_run(body.run_id, body.course_id, body.course, body.session_id)
        finally:
            LECTURE_NOTES.discard(body.run_id)

    # A sync function: Starlette runs it in a thread, off the event loop.
    background.add_task(execute)
    return LectureNotesResponse(started=True)


@app.post("/lecture-notes/cancel")
async def cancel_lecture_notes(body: LectureNotesCancel) -> LectureNotesCancelResponse:
    from app.note_taker.lecture_notes import runs

    event = runs.CANCEL.get(body.run_id)
    if event is not None:
        event.set()
    return LectureNotesCancelResponse(cancelled=event is not None)


@app.get("/health")
def health(
    settings: Annotated[WorkerSettings, Depends(get_worker_settings)],
) -> dict[str, str]:
    return {"status": "ok", "environment": settings.environment}
