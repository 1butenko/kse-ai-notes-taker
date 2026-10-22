import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, TypeAdapter

from app.config import Settings, get_settings
from app.note_assets import MAX_UPLOAD_BYTES, import_asset, load_asset, validated_asset_path
from app.notes import (
    NoteAsset,
    NotesDocument,
    NotesRun,
    RenderedArtifact,
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

DOWNLOADS = {
    "pdf": ("notes.pdf", "application/pdf"),
    "qmd": ("notes.qmd", "text/markdown"),
    "html": ("notes.html", "text/html"),
    "docx": (
        "notes.docx",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ),
}

# Applied to the response as well as the preview iframe: opening HTML directly
# must retain the opaque origin and cannot read application cookies or storage.
HTML_HEADERS = {
    "Content-Security-Policy": (
        "sandbox allow-scripts; default-src 'none'; "
        "script-src 'unsafe-inline' data: https://cdn.jsdelivr.net/npm/mathjax@3/; "
        "style-src 'unsafe-inline' data:; img-src data:; "
        "font-src data: https://cdn.jsdelivr.net/npm/mathjax@3/; connect-src 'none'; "
        "base-uri 'none'; form-action 'none'"
    ),
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
}


class NotesRunRequest(BaseModel):
    resume: str | None = None


class NotesRunView(BaseModel):
    run: NotesRun
    document: NotesDocument | None
    pdf: bool
    topic_pdfs: list[str]
    artifacts: list[RenderedArtifact] = Field(default_factory=list)


def find_run(settings: Settings, course: str, run: str) -> NotesRun:
    found = load_run(course_dir(settings, course), run)
    if found is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Notes run not found")
    return found


def view(settings: Settings, course: str, run: NotesRun) -> NotesRunView:
    directory = course_dir(settings, course)
    document = load_document(directory, run.id) if run.status == "done" else None
    topics = [t.topic_id for s in document.sections for t in s.topics] if document else []
    manifest = run_dir(directory, run.id) / "artifacts.json"
    return NotesRunView(
        run=run,
        document=document,
        pdf=(run_dir(directory, run.id) / "notes.pdf").is_file(),
        topic_pdfs=[t for t in topics if topic_pdf(directory, run.id, t).is_file()],
        artifacts=(
            TypeAdapter(list[RenderedArtifact]).validate_json(manifest.read_text())
            if manifest.is_file()
            else []
        ),
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


class NoteAssetUpload(BaseModel):
    asset: NoteAsset
    markdown_path: str


@router.post("/{course}/notes/{run}/assets", status_code=status.HTTP_201_CREATED)
async def upload_note_asset(
    course: str,
    run: str,
    file: UploadFile,
    settings: Annotated[Settings, Depends(get_settings)],
) -> NoteAssetUpload:
    """Import a resource without changing the saved note content or its revision."""
    find_run(settings, course, run)
    try:
        data = await file.read(MAX_UPLOAD_BYTES + 1)
        if len(data) > MAX_UPLOAD_BYTES:
            raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "Image exceeds 10 MiB")
        asset = await asyncio.to_thread(
            import_asset,
            run_dir(course_dir(settings, course), run),
            data,
            file.filename or "image",
        )
    except ValueError as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error)) from error
    finally:
        await file.close()
    return NoteAssetUpload(asset=asset, markdown_path=asset.path)


@router.get("/{course}/notes/{run}/assets/{asset_id}")
def download_note_asset(
    course: str,
    run: str,
    asset_id: str,
    settings: Annotated[Settings, Depends(get_settings)],
) -> FileResponse:
    find_run(settings, course, run)
    directory = run_dir(course_dir(settings, course), run)
    try:
        asset = load_asset(directory, asset_id)
        path = validated_asset_path(directory, asset)
    except (ValueError, OSError) as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Note asset not found") from error
    return FileResponse(
        path,
        media_type=asset.media_type,
        filename=asset.name,
        content_disposition_type="inline",
        headers={"X-Content-Type-Options": "nosniff"},
    )


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
    return FileResponse(
        file,
        media_type=media,
        filename=name,
        content_disposition_type="inline",
        headers=HTML_HEADERS if kind == "html" else None,
    )


@router.get("/{course}/notes/{run}/topics/{topic}/{kind}")
def download_topic(
    course: str,
    run: str,
    topic: str,
    kind: str,
    settings: Annotated[Settings, Depends(get_settings)],
) -> FileResponse:
    if kind not in ("html", "pdf"):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown download")
    find_run(settings, course, run)
    document = load_document(course_dir(settings, course), run)
    if document is None or topic not in {t.topic_id for s in document.sections for t in s.topics}:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Topic not found")
    root = run_dir(course_dir(settings, course), run).resolve()
    file = (root / "topics" / topic / f"note.{kind}").resolve()
    if not file.is_relative_to(root / "topics"):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Topic not found")
    if not file.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No {kind.upper()} for this topic")
    return FileResponse(
        file,
        media_type=DOWNLOADS[kind][1],
        filename=f"notes-{topic}.{kind}",
        content_disposition_type="inline",
        headers=HTML_HEADERS if kind == "html" else None,
    )
