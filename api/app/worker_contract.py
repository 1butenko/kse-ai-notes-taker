"""What the API and the worker send each other."""

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
