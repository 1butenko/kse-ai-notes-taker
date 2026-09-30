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
