"""What the API and the worker send each other."""

from uuid import UUID

from pydantic import BaseModel

from app.plan import BookMatch, Plan, Proposal
from app.syllabus import SyllabusExtraction, Transcript


class TranscribeRequest(BaseModel):
    path: str
    force: bool = False


class TranscribeResponse(BaseModel):
    extraction: SyllabusExtraction
    model: str


class MapRequest(BaseModel):
    course: str
    plan: Plan
    transcript: Transcript
    books: list[str]


class MapResponse(BaseModel):
    matches: list[BookMatch]
    proposals: list[Proposal]


class BooksRequest(BaseModel):
    course: str


class BooksResponse(BaseModel):
    """Whether the pages of the course's approved excerpts are being transcribed."""

    started: bool


class NoteTakerRequest(BaseModel):
    """One AI Note Taker run, already recorded in `sync_runs` by the API."""

    run_id: UUID
    course_id: UUID
    moodle_course_id: int
    focus: str | None = None


class NoteTakerResponse(BaseModel):
    started: bool


class LectureNotesRequest(BaseModel):
    """One lecture-notes run, already recorded in `lecture_note_runs` by the API."""

    run_id: UUID
    course_id: UUID
    course: str  # the app's course key (uploads folder)
    session_id: str


class LectureNotesResponse(BaseModel):
    started: bool


class LectureNotesCancel(BaseModel):
    run_id: UUID


class LectureNotesCancelResponse(BaseModel):
    # False when the worker is not running it (already finished, or lost in a restart).
    cancelled: bool
