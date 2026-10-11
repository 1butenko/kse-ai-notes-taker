import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, status

from app.notes import RUN_ID
from app.storage import sha256
from app.syllabus import SyllabusExtraction
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
    MapRequest,
    MapResponse,
    NotesRequest,
    NotesResponse,
    TranscribeRequest,
    TranscribeResponse,
)

COURSE = re.compile(r"^(local|\d+)$")

settings = get_worker_settings()
langfuse = init_langfuse(settings)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    fail_interrupted(settings.uploads_dir)
    yield
    langfuse.shutdown()


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

    store = open_run(
        settings.uploads_dir / body.course,
        body.course,
        body.run,
        NotesModels.from_settings(settings),
    )
    ACTIVE.add(body.course)
    background.add_task(run_notes, opener, settings, store, body.plan, body.transcript)
    return store.run


@app.get("/health")
def health(
    settings: Annotated[WorkerSettings, Depends(get_worker_settings)],
) -> dict[str, str]:
    return {"status": "ok", "environment": settings.environment}
