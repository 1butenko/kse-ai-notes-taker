import hashlib
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import httpx2
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ValidationError

from app.config import Settings, get_settings
from app.openrouter import OpenRouterClient, OpenRouterError, get_openrouter_client
from app.syllabus import (
    EmptyDocument,
    SyllabusExtraction,
    Transcript,
    build_messages,
    drop_bad_refs,
    strict_schema,
)

router = APIRouter(prefix="/syllabus", tags=["syllabus"])

ALLOWED_SUFFIXES = {".pdf", ".docx"}
MAX_SIZE = 20 * 1024 * 1024
SCHEMA = strict_schema(SyllabusExtraction)


class TranscribeRequest(BaseModel):
    path: str


def syllabus_file(settings: Settings, path: str) -> Path:
    root = settings.uploads_dir.resolve()
    file = (root / path).resolve()
    if not file.is_relative_to(root):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Path is outside the uploads directory")
    relative = file.relative_to(root).parts
    if len(relative) != 3 or relative[1] != "syllabus":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Not a syllabus file")
    if not file.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Syllabus file not found")
    if file.suffix.lower() not in ALLOWED_SUFFIXES:
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "Only PDF and DOCX syllabi can be transcribed"
        )
    if file.stat().st_size > MAX_SIZE:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "Syllabus file is larger than 20 MB")
    return file


def transcript_file(file: Path) -> Path:
    return file.with_name(f"{file.name}.transcript.json")


def load_transcript(file: Path) -> Transcript | None:
    target = transcript_file(file)
    if not target.is_file():
        return None
    try:
        return Transcript.model_validate_json(target.read_text())
    except ValidationError:
        return None


def sha256(file: Path) -> str:
    with file.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


@router.post("/transcribe")
async def transcribe(
    body: TranscribeRequest,
    settings: Annotated[Settings, Depends(get_settings)],
    client: Annotated[OpenRouterClient | None, Depends(get_openrouter_client)],
    force: Annotated[bool, Query()] = False,
) -> Transcript:
    file = syllabus_file(settings, body.path)
    digest = sha256(file)

    cached = load_transcript(file)
    if cached and not force and cached.source_sha256 == digest:
        return cached

    if client is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Transcription is not configured")

    try:
        messages, plugins = build_messages(file)
    except EmptyDocument as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error)) from error

    try:
        content = await client.complete_json(messages, "syllabus", SCHEMA, plugins)
    except httpx2.TimeoutException as error:
        print(f"OpenRouter timed out: {error!r}")
        raise HTTPException(status.HTTP_504_GATEWAY_TIMEOUT, "The model timed out") from error
    except (OpenRouterError, httpx2.HTTPError) as error:
        print(f"OpenRouter request failed: {error!r}")
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "The model request failed") from error

    try:
        extraction = SyllabusExtraction.model_validate_json(content)
    except ValidationError as error:
        print(f"Model returned an invalid transcript: {error}")
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, "The model returned an invalid transcript"
        ) from error
    drop_bad_refs(extraction)

    transcript = Transcript(
        **extraction.model_dump(),
        source_path=file.relative_to(settings.uploads_dir.resolve()).as_posix(),
        source_sha256=digest,
        model=client.model,
        created_at=datetime.now(UTC).isoformat(),
    )
    transcript_file(file).write_text(transcript.model_dump_json(indent=2))
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
