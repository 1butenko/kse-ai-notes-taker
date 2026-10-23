import asyncio
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.config import Settings, get_settings
from app.note_assets import MAX_UPLOAD_BYTES, import_asset, load_asset, validated_asset_path
from app.notes import (
    NoteAsset,
    NotesDocument,
    NotesRun,
    RenderedArtifact,
    RenderFormat,
    list_runs,
    load_document,
    load_run,
    new_run_id,
    run_dir,
    topic_pdf,
)
from app.notes_artifacts import artifact_path, read_job, revision_jobs, selected_artifacts
from app.notes_revisions import (
    EditResult,
    RenderJob,
    RevisionConflict,
    RevisionInfo,
    RevisionNotFound,
    RevisionStore,
    RevisionView,
    TopicPatch,
)
from app.routers.plans import course_dir, current
from app.worker_client import WorkerClient, get_worker_client
from app.worker_contract import NotesRequest, RenderRequest, RestoreRequest, ReviseRequest

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
    # The current (HEAD) revision's document; artifacts carry the revision they show.
    document: NotesDocument | None
    current_revision: int = 0
    display_revision: int | None = None
    render: RenderJob | None = None
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
    root = run_dir(directory, run.id)
    artifacts: list[RenderedArtifact] = []
    jobs: list[RenderJob] = []
    try:
        head = RevisionStore(root).current() if run.status == "done" else None
        if head:
            # HEAD may advance between reads: never show a revision newer than this view.
            artifacts = selected_artifacts(root, through=head.info.revision)
            jobs = revision_jobs(root, head.info.revision)
    except RevisionNotFound:
        head = None
    except (OSError, ValueError, RevisionConflict) as error:
        raise HTTPException(409, "Stored revision history is unreadable") from error
    document = head.document if head else None
    topics = [t.topic_id for s in document.sections for t in s.topics] if document else []
    ready = [a for a in artifacts if a.status == "ready"]
    full = next(
        (a for kind in ("html", "pdf") for a in ready if a.topic_id is None and a.format == kind),
        None,
    )
    return NotesRunView(
        run=run,
        document=document,
        current_revision=head.info.revision if head else 0,
        display_revision=full.revision if full else (0 if (root / "notes.pdf").is_file() else None),
        render=jobs[-1] if jobs else None,
        pdf=any(a.format == "pdf" and a.topic_id is None for a in ready)
        or (root / "notes.pdf").is_file(),
        topic_pdfs=[
            t
            for t in topics
            if any(a.format == "pdf" and a.topic_id == t for a in ready)
            or topic_pdf(directory, run.id, t).is_file()
        ],
        artifacts=artifacts,
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


def revision_store(settings: Settings, course: str, run: str) -> RevisionStore:
    """The committed history of a completed run; reading it never writes."""
    if find_run(settings, course, run).status != "done":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Notes are not ready")
    return RevisionStore(run_dir(course_dir(settings, course), run))


@router.get("/{course}/notes/{run}/revisions")
def get_revisions(
    course: str, run: str, settings: Annotated[Settings, Depends(get_settings)]
) -> list[RevisionInfo]:
    try:
        return revision_store(settings, course, run).list()
    except RevisionNotFound as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(error)) from error


@router.get("/{course}/notes/{run}/revisions/{revision}")
def get_revision(
    course: str, run: str, revision: int, settings: Annotated[Settings, Depends(get_settings)]
) -> RevisionView:
    try:
        return revision_store(settings, course, run).read(revision)
    except RevisionNotFound as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(error)) from error


@router.patch("/{course}/notes/{run}/topics/{topic}")
async def save_topic(
    course: str,
    run: str,
    topic: str,
    patch: TopicPatch,
    settings: Annotated[Settings, Depends(get_settings)],
    worker: Annotated[WorkerClient, Depends(get_worker_client)],
) -> EditResult:
    """Save one topic's complete block list as a new revision of the notes."""
    find_run(settings, course, run)
    return await worker.revise_notes(
        ReviseRequest(course=course, run=run, topic=topic, patch=patch)
    )


class RestoreBody(BaseModel):
    base_revision: int = Field(ge=0)


@router.post("/{course}/notes/{run}/revisions/{revision}/restore")
async def restore_revision(
    course: str,
    run: str,
    revision: int,
    body: RestoreBody,
    settings: Annotated[Settings, Depends(get_settings)],
    worker: Annotated[WorkerClient, Depends(get_worker_client)],
) -> EditResult:
    """Copy an earlier revision's content into a new revision; the history is kept."""
    find_run(settings, course, run)
    return await worker.restore_notes(
        RestoreRequest(course=course, run=run, revision=revision, base_revision=body.base_revision)
    )


class RenderBody(BaseModel):
    formats: list[RenderFormat] = Field(min_length=1)


@router.post("/{course}/notes/{run}/revisions/{revision}/render", status_code=202)
async def render_revision(
    course: str,
    run: str,
    revision: int,
    body: RenderBody,
    settings: Annotated[Settings, Depends(get_settings)],
    worker: Annotated[WorkerClient, Depends(get_worker_client)],
) -> RenderJob:
    revision_store(settings, course, run)
    return await worker.render_notes(
        RenderRequest(course=course, run=run, revision=revision, formats=body.formats)
    )


@router.get("/{course}/notes/{run}/render-jobs/{job}")
def get_render_job(
    course: str, run: str, job: str, settings: Annotated[Settings, Depends(get_settings)]
) -> RenderJob:
    store = revision_store(settings, course, run)
    try:
        return read_job(store.directory, job)
    except (RevisionNotFound, OSError, ValueError) as error:
        raise HTTPException(404, "Render job not found") from error


def served(
    path: Path, kind: str, revision: int, filename: str, media: str | None = None
) -> FileResponse:
    """Every served file names the revision it was rendered from."""
    headers = {**(HTML_HEADERS if kind == "html" else {}), "X-Notes-Revision": str(revision)}
    return FileResponse(
        path,
        media_type=media or DOWNLOADS[kind][1],
        filename=filename,
        content_disposition_type="inline",
        headers=headers,
    )


def revision_download(
    settings: Settings, course: str, run: str, revision: int, kind: str, topic: str | None = None
) -> FileResponse:
    """An explicit revision's own file; it never falls back to another revision."""
    if kind not in ("html", "pdf", "docx"):
        raise HTTPException(404, "Unknown download")
    store = revision_store(settings, course, run)
    try:
        path = artifact_path(store.directory, revision, kind, topic)
    except RevisionNotFound as error:
        raise HTTPException(404, str(error)) from error
    except (OSError, ValueError, RevisionConflict) as error:
        raise HTTPException(409, "Stored revision history is unreadable") from error
    return served(path, kind, revision, f"notes-{topic}.{kind}" if topic else f"notes.{kind}")


def latest_ready(
    settings: Settings, course: str, run: NotesRun, kind: str, topic: str | None
) -> int | None:
    """Legacy URLs alias the newest committed ready file; the response names its revision."""
    if run.status != "done":
        return None
    try:
        artifacts = selected_artifacts(run_dir(course_dir(settings, course), run.id))
    except (RevisionNotFound, RevisionConflict, OSError, ValueError):
        return None
    return next(
        (
            a.revision
            for a in artifacts
            if (a.format, a.topic_id, a.status) == (kind, topic, "ready")
        ),
        None,
    )


@router.get("/{course}/notes/{run}/revisions/{revision}/artifacts/{kind}")
def download_revision(
    course: str,
    run: str,
    revision: int,
    kind: str,
    settings: Annotated[Settings, Depends(get_settings)],
) -> FileResponse:
    return revision_download(settings, course, run, revision, kind)


@router.get("/{course}/notes/{run}/revisions/{revision}/topics/{topic}/artifacts/{kind}")
def download_revision_topic(
    course: str,
    run: str,
    revision: int,
    topic: str,
    kind: str,
    settings: Annotated[Settings, Depends(get_settings)],
) -> FileResponse:
    return revision_download(settings, course, run, revision, kind, topic)


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
    found = find_run(settings, course, run)
    revision = latest_ready(settings, course, found, kind, None) if kind != "qmd" else None
    if revision is not None:
        return revision_download(settings, course, run, revision, kind)
    # The generation's own files, including the Quarto source: revision 0.
    name, media = DOWNLOADS[kind]
    file = run_dir(course_dir(settings, course), run) / name
    if not file.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No {kind} for this run")
    return served(file, kind, 0, name, media)


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
    revision = latest_ready(settings, course, find_run(settings, course, run), kind, topic)
    if revision is not None:
        return revision_download(settings, course, run, revision, kind, topic)
    document = load_document(course_dir(settings, course), run)
    if document is None or topic not in {t.topic_id for s in document.sections for t in s.topics}:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Topic not found")
    root = run_dir(course_dir(settings, course), run).resolve()
    file = (root / "topics" / topic / f"note.{kind}").resolve()
    if not file.is_relative_to(root / "topics"):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Topic not found")
    if not file.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No {kind.upper()} for this topic")
    return served(file, kind, 0, f"notes-{topic}.{kind}")
