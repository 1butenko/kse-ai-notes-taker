from pathlib import Path

from pydantic import ValidationError

from app.schemas import Strict


class Reading(Strict):
    raw: str
    title: str | None
    authors: list[str]
    year: str | None
    url: str | None
    pages: str | None


class SessionReading(Reading):
    material_ref: int | None


class Session(Strict):
    label: str
    number: int | None
    date: str | None
    topic: str
    subtopics: list[str]
    required_readings: list[SessionReading]
    optional_readings: list[SessionReading]


class SyllabusExtraction(Strict):
    language: str | None
    learning_materials: list[Reading]
    sessions: list[Session]
    notes: str | None


class Transcript(SyllabusExtraction):
    source_path: str
    source_sha256: str
    model: str
    created_at: str


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
