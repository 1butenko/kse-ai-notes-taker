from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from app.config import Settings, get_settings
from app.plan import drop_primary, load_plan, save_plan, sync
from app.storage import sha256
from app.syllabus import Transcript, load_transcript, transcript_file
from app.worker_client import WorkerClient, get_worker_client
from app.worker_contract import TranscribeRequest as WorkerTranscribeRequest

router = APIRouter(prefix="/syllabus", tags=["syllabus"])

ALLOWED_SUFFIXES = {".pdf", ".docx"}
MAX_SIZE = 20 * 1024 * 1024


class TranscribeRequest(BaseModel):
    path: str


def stored_syllabus(settings: Settings, path: str) -> Path:
    root = settings.uploads_dir.resolve()
    file = (root / path).resolve()
    if not file.is_relative_to(root):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Path is outside the uploads directory")
    relative = file.relative_to(root).parts
    if len(relative) != 3 or relative[1] != "syllabus" or file.name.endswith(".transcript.json"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Not a syllabus file")
    if not file.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Syllabus file not found")
    return file


def syllabus_file(settings: Settings, path: str) -> Path:
    """A stored syllabus that can be transcribed."""
    file = stored_syllabus(settings, path)
    if file.suffix.lower() not in ALLOWED_SUFFIXES:
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "Only PDF and DOCX syllabi can be transcribed"
        )
    if file.stat().st_size > MAX_SIZE:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "Syllabus file is larger than 20 MB")
    return file


def use_as_plan_if_first(settings: Settings, source_path: str) -> None:
    course_dir = settings.uploads_dir / source_path.split("/")[0]
    plan = load_plan(course_dir)
    if plan.primary is None:
        plan.primary = source_path
        save_plan(course_dir, plan)


@router.post("/transcribe")
async def transcribe(
    body: TranscribeRequest,
    settings: Annotated[Settings, Depends(get_settings)],
    worker: Annotated[WorkerClient, Depends(get_worker_client)],
    force: Annotated[bool, Query()] = False,
) -> Transcript:
    file = syllabus_file(settings, body.path)
    digest = sha256(file)

    cached = load_transcript(file)
    if cached and not force and cached.source_sha256 == digest:
        use_as_plan_if_first(settings, cached.source_path)
        return cached

    reply = await worker.transcribe(WorkerTranscribeRequest(path=body.path, force=force))

    transcript = Transcript(
        **reply.extraction.model_dump(),
        source_path=file.relative_to(settings.uploads_dir.resolve()).as_posix(),
        source_sha256=digest,
        model=reply.model,
        created_at=datetime.now(UTC).isoformat(),
    )
    transcript_file(file).write_text(transcript.model_dump_json(indent=2))
    use_as_plan_if_first(settings, transcript.source_path)
    print(
        f"Transcribed {transcript.source_path}: {len(transcript.sessions)} sessions, "
        f"{len(transcript.learning_materials)} materials"
    )
    return transcript


@router.get("/transcript")
def get_transcript(
    path: Annotated[str, Query()],
    settings: Annotated[Settings, Depends(get_settings)],
) -> Transcript:
    transcript = load_transcript(syllabus_file(settings, path))
    if transcript is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No transcript for this file yet")
    return transcript


@router.put("/transcript")
def put_transcript(
    path: Annotated[str, Query()],
    body: Transcript,
    settings: Annotated[Settings, Depends(get_settings)],
) -> Transcript:
    """Save the lecturer's edits (renamed, removed or added sessions) to a transcript."""
    file = syllabus_file(settings, path)
    stored = load_transcript(file)
    if stored is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No transcript for this file yet")
    # Provenance stays the stored one, so the edit still counts as this file's transcript.
    transcript = body.model_copy(
        update={
            "source_path": stored.source_path,
            "source_sha256": stored.source_sha256,
            "model": stored.model,
            "created_at": stored.created_at,
        }
    )
    transcript_file(file).write_text(transcript.model_dump_json(indent=2))

    # As after a re-transcription: unmatched sessions' files move to `unassigned`.
    course_dir = settings.uploads_dir / transcript.source_path.split("/")[0]
    plan = load_plan(course_dir)
    if plan.primary == transcript.source_path and sync(plan, transcript):
        save_plan(course_dir, plan)
    print(f"Edited transcript {transcript.source_path}: {len(transcript.sessions)} sessions")
    return transcript


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
def delete_syllabus(
    path: Annotated[str, Query()],
    settings: Annotated[Settings, Depends(get_settings)],
) -> None:
    file = stored_syllabus(settings, path)
    relative = file.relative_to(settings.uploads_dir.resolve()).as_posix()
    course_dir = settings.uploads_dir / relative.split("/")[0]

    plan = load_plan(course_dir)
    if plan.primary == relative:
        drop_primary(plan)
        save_plan(course_dir, plan)

    transcript_file(file).unlink(missing_ok=True)
    file.unlink()
    print(f"Deleted syllabus: {relative}")
