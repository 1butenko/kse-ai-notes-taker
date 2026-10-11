from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.config import Settings, get_settings
from app.notes import (
    NotesDocument,
    NotesRun,
    list_runs,
    load_document,
    load_run,
    new_run_id,
    run_dir,
    topic_pdf,
)
from app.routers.plans import course_dir, current
from app.worker_client import WorkerClient, get_worker_client
from app.worker_contract import NotesRequest

router = APIRouter(prefix="/plans", tags=["notes"])

DOWNLOADS = {"pdf": ("notes.pdf", "application/pdf"), "qmd": ("notes.qmd", "text/markdown")}


class NotesRunRequest(BaseModel):
    resume: str | None = None


class NotesRunView(BaseModel):
    run: NotesRun
    document: NotesDocument | None
    pdf: bool
    topic_pdfs: list[str]


def find_run(settings: Settings, course: str, run: str) -> NotesRun:
    found = load_run(course_dir(settings, course), run)
    if found is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Notes run not found")
    return found


def view(settings: Settings, course: str, run: NotesRun) -> NotesRunView:
    directory = course_dir(settings, course)
    document = load_document(directory, run.id) if run.status == "done" else None
    topics = [t.topic_id for s in document.sections for t in s.topics] if document else []
    return NotesRunView(
        run=run,
        document=document,
        pdf=(run_dir(directory, run.id) / "notes.pdf").is_file(),
        topic_pdfs=[t for t in topics if topic_pdf(directory, run.id, t).is_file()],
    )


@router.post("/{course}/notes", status_code=status.HTTP_202_ACCEPTED)
async def generate_notes(
    course: str,
    settings: Annotated[Settings, Depends(get_settings)],
    worker: Annotated[WorkerClient, Depends(get_worker_client)],
    body: NotesRunRequest | None = None,
) -> NotesRunView:
    """Start a notes run for the course plan, or resume an earlier one by its id."""
    plan, transcript = current(settings, course)
    if transcript is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Transcribe a syllabus first")
    if not any(s.files for s in plan.sessions):
        raise HTTPException(status.HTTP_409_CONFLICT, "Attach materials to the sessions first")

    run_id = body.resume if body and body.resume else new_run_id()
    if body and body.resume:
        find_run(settings, course, run_id)

    started = await worker.generate_notes(
        NotesRequest(course=course, run=run_id, plan=plan, transcript=transcript)
    )
    run = load_run(course_dir(settings, course), started.id) or started
    return view(settings, course, run)


@router.get("/{course}/notes")
def get_runs(course: str, settings: Annotated[Settings, Depends(get_settings)]) -> list[NotesRun]:
    return list_runs(course_dir(settings, course))


@router.get("/{course}/notes/{run}")
def get_run(
    course: str, run: str, settings: Annotated[Settings, Depends(get_settings)]
) -> NotesRunView:
    return view(settings, course, find_run(settings, course, run))


@router.get("/{course}/notes/{run}/{kind}")
def download(
    course: str, run: str, kind: str, settings: Annotated[Settings, Depends(get_settings)]
) -> FileResponse:
    if kind not in DOWNLOADS:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown download")
    find_run(settings, course, run)
    name, media = DOWNLOADS[kind]
    file = run_dir(course_dir(settings, course), run) / name
    if not file.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No {kind} for this run")
    return FileResponse(file, media_type=media, filename=name, content_disposition_type="inline")


@router.get("/{course}/notes/{run}/topics/{topic}/pdf")
def download_topic(
    course: str,
    run: str,
    topic: str,
    settings: Annotated[Settings, Depends(get_settings)],
) -> FileResponse:
    find_run(settings, course, run)
    document = load_document(course_dir(settings, course), run)
    if document is None or topic not in {t.topic_id for s in document.sections for t in s.topics}:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Topic not found")
    file = topic_pdf(course_dir(settings, course), run, topic)
    if not file.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No PDF for this topic")
    return FileResponse(
        file,
        media_type="application/pdf",
        filename=f"notes-{topic}.pdf",
        content_disposition_type="inline",
    )
