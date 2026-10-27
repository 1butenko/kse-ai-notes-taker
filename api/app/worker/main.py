import asyncio
import fcntl
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, status

from app.notes import RUN_ID, run_dir
from app.notes_revisions import (
    EditResult,
    InvalidEdit,
    RenderJob,
    RevisionConflict,
    RevisionNotFound,
)
from app.notes_suggestions import NoteSuggestion, VerificationJob
from app.storage import sha256
from app.syllabus import SyllabusExtraction
from app.worker import note_suggestions, revisions
from app.worker.config import WorkerSettings, get_worker_settings
from app.worker.llm import ask
from app.worker.mapping import proposal_summary, run_mapping
from app.worker.models import NotesModels
from app.worker.notes import ACTIVE, fail_interrupted, open_run, run_notes
from app.worker.openrouter import (
    Opener,
    OpenRouterClient,
    get_openrouter_client,
    get_openrouter_opener,
)
from app.worker.tracing import course_trace, init_langfuse
from app.worker.transcribe import EmptyDocument, build_messages, drop_bad_refs
from app.worker_contract import (
    ApprovalRequest,
    MapRequest,
    MapResponse,
    NotesRequest,
    NotesResponse,
    RenderRequest,
    RestoreRequest,
    ReviseRequest,
    SuggestionActionRequest,
    SuggestRequest,
    TranscribeRequest,
    TranscribeResponse,
    VerifyTopicRequest,
)

COURSE = re.compile(r"^(local|\d+)$")

settings = get_worker_settings()
langfuse = init_langfuse(settings)


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
            await asyncio.to_thread(fail_interrupted, settings.uploads_dir)
            await asyncio.to_thread(revisions.fail_interrupted_renders, settings.uploads_dir)
            await asyncio.to_thread(note_suggestions.fail_interrupted_jobs, settings.uploads_dir)
            yield
        finally:
            langfuse.shutdown()
            fcntl.flock(lock, fcntl.LOCK_UN)


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

    source_path = file.relative_to(settings.uploads_dir.resolve()).as_posix()
    with course_trace(
        "transcribe-syllabus", source_path.split("/")[0], {"syllabus": file.name}
    ) as span:
        span.update(metadata={"path": source_path, "sha256": sha256(file), "forced": body.force})
        extraction = await ask(
            client, messages, SyllabusExtraction, "transcript", plugins, step="extract-reading-plan"
        )
        dropped = drop_bad_refs(extraction)
        span.update(
            output={
                "language": extraction.language,
                "learning_materials": len(extraction.learning_materials),
                "sessions": len(extraction.sessions),
                "readings": sum(
                    len(s.required_readings) + len(s.optional_readings) for s in extraction.sessions
                ),
                "notes": extraction.notes,
            },
        )
        if dropped:
            span.update(level="WARNING", status_message=f"Dropped {dropped} bad material_ref")

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
    with course_trace(
        "map-materials",
        body.course,
        {"materials": [m.raw for m in body.transcript.learning_materials], "books": body.books},
    ) as span:
        matches, proposals = await run_mapping(
            client, settings.uploads_dir, directory, body.plan, body.transcript, body.books
        )
        span.update(
            output={
                "books": [m.model_dump(include={"raw", "file"}) for m in matches if m.file],
                "proposals": [proposal_summary(p) for p in proposals],
            }
        )
    return MapResponse(matches=matches, proposals=proposals)


@app.post("/notes", status_code=status.HTTP_202_ACCEPTED)
async def generate_notes(
    body: NotesRequest,
    background: BackgroundTasks,
    settings: Annotated[WorkerSettings, Depends(get_worker_settings)],
    opener: Annotated[Opener | None, Depends(get_openrouter_opener)],
) -> NotesResponse:
    """Start (or resume) a notes run; it continues after the response, see run.json."""
    if not COURSE.match(body.course):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Invalid course: {body.course!r}")
    if not RUN_ID.match(body.run):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Invalid run: {body.run!r}")
    if opener is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Notes are not configured")
    if body.course in ACTIVE:
        raise HTTPException(status.HTTP_409_CONFLICT, "Notes are already being generated")

    ACTIVE.add(body.course)  # Reserved before admission waits for the run lock off the loop.
    try:
        store = await asyncio.to_thread(
            open_run,
            settings.uploads_dir / body.course,
            body.course,
            body.run,
            NotesModels.from_settings(settings),
            body.plan,
            body.transcript,
            body.session_id,
        )
    except RevisionConflict as error:
        ACTIVE.discard(body.course)
        raise HTTPException(status.HTTP_409_CONFLICT, str(error)) from error
    except BaseException:
        ACTIVE.discard(body.course)
        raise
    background.add_task(run_notes, opener, settings, store, body.plan, body.transcript)
    return store.run


def run_directory(settings: WorkerSettings, course: str, run: str) -> Path:
    if not COURSE.match(course):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Invalid course: {course!r}")
    if not RUN_ID.match(run):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Invalid run: {run!r}")
    return run_dir(settings.uploads_dir / course, run)


@app.post("/notes/revise")
async def revise_notes(
    body: ReviseRequest,
    background: BackgroundTasks,
    settings: Annotated[WorkerSettings, Depends(get_worker_settings)],
) -> EditResult:
    """Save one topic's blocks as a new immutable revision, without a model."""
    directory = run_directory(settings, body.course, body.run)
    result = await revisions.revise(directory, body.topic, body.patch)
    if result.render:
        background.add_task(revisions.render_revision, directory, result.render.id, settings)
    return result


@app.post("/notes/restore")
async def restore_notes(
    body: RestoreRequest,
    background: BackgroundTasks,
    settings: Annotated[WorkerSettings, Depends(get_worker_settings)],
) -> EditResult:
    """Copy an earlier revision's content into a new revision, without a model."""
    directory = run_directory(settings, body.course, body.run)
    result = await revisions.restore(directory, body.revision, body.base_revision)
    if result.render:
        background.add_task(revisions.render_revision, directory, result.render.id, settings)
    return result


@app.post("/notes/approval")
async def decide_notes(
    body: ApprovalRequest,
    background: BackgroundTasks,
    settings: Annotated[WorkerSettings, Depends(get_worker_settings)],
) -> EditResult:
    directory = run_directory(settings, body.course, body.run)
    result = await revisions.decide(directory, body.topic, body.action)
    if result.render:
        background.add_task(revisions.render_revision, directory, result.render.id, settings)
    return result


@app.post("/notes/suggestions", status_code=status.HTTP_202_ACCEPTED)
async def suggest_notes(
    body: SuggestRequest,
    background: BackgroundTasks,
    settings: Annotated[WorkerSettings, Depends(get_worker_settings)],
    opener: Annotated[Opener | None, Depends(get_openrouter_opener)],
) -> NoteSuggestion:
    """Prepare a proposal for some blocks of one topic; it changes nothing until applied."""
    directory = run_directory(settings, body.course, body.run)
    if opener is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "AI suggestions are not configured"
        )
    record = await revisions.guarded(
        lambda: note_suggestions.create_suggestion(directory, body.suggestion)
    )
    background.add_task(note_suggestions.run_suggestion, directory, record.id, settings, opener)
    return record.public()


@app.post("/notes/suggestions/apply")
async def apply_suggestion(
    body: SuggestionActionRequest,
    background: BackgroundTasks,
    settings: Annotated[WorkerSettings, Depends(get_worker_settings)],
) -> EditResult:
    """Commit a ready suggestion as a new revision, once."""
    directory = run_directory(settings, body.course, body.run)
    if body.base_revision is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "base_revision is required")
    result, _ = await note_suggestions.apply(directory, body.suggestion, body.base_revision)
    if result.render:
        background.add_task(revisions.render_revision, directory, result.render.id, settings)
    return result


@app.post("/notes/suggestions/reject")
async def reject_suggestion(
    body: SuggestionActionRequest,
    settings: Annotated[WorkerSettings, Depends(get_worker_settings)],
) -> NoteSuggestion:
    directory = run_directory(settings, body.course, body.run)
    record = await revisions.guarded(
        lambda: note_suggestions.reject_suggestion(directory, body.suggestion)
    )
    return record.public()


@app.post("/notes/verify", status_code=status.HTTP_202_ACCEPTED)
async def verify_topic(
    body: VerifyTopicRequest,
    background: BackgroundTasks,
    settings: Annotated[WorkerSettings, Depends(get_worker_settings)],
    opener: Annotated[Opener | None, Depends(get_openrouter_opener)],
) -> VerificationJob:
    """Check one topic's saved text against its evidence, without rewriting anything."""
    directory = run_directory(settings, body.course, body.run)
    if opener is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Verification is not configured")
    job = await revisions.guarded(
        lambda: note_suggestions.create_verification(directory, body.topic, body.base_revision)
    )
    background.add_task(note_suggestions.run_verification, directory, job.id, settings, opener)
    return job


@app.post("/notes/render", status_code=status.HTTP_202_ACCEPTED)
async def render_saved_notes(
    body: RenderRequest,
    background: BackgroundTasks,
    settings: Annotated[WorkerSettings, Depends(get_worker_settings)],
) -> RenderJob:
    directory = run_directory(settings, body.course, body.run)
    try:
        job = await asyncio.to_thread(
            revisions.enqueue_render, directory, body.revision, body.formats
        )
    except RevisionNotFound as error:
        raise HTTPException(404, str(error)) from error
    except InvalidEdit as error:
        raise HTTPException(422, str(error)) from error
    except RevisionConflict as error:
        raise HTTPException(409, str(error)) from error
    background.add_task(revisions.render_revision, directory, job.id, settings)
    return job


@app.get("/health")
def health(
    settings: Annotated[WorkerSettings, Depends(get_worker_settings)],
) -> dict[str, str]:
    return {"status": "ok", "environment": settings.environment}
