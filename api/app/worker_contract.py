"""What the API and the worker send each other."""

from pydantic import BaseModel

from app.notes import NotesRun, RenderFormat
from app.notes_revisions import ApprovalAction, TopicPatch
from app.notes_suggestions import SuggestionRequest
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


class NotesRequest(BaseModel):
    course: str
    run: str
    plan: Plan
    transcript: Transcript
    # A lecture run: plan and transcript are already scoped to this one session.
    session_id: str | None = None


NotesResponse = NotesRun


class ReviseRequest(BaseModel):
    course: str
    run: str
    topic: str
    patch: TopicPatch


class RestoreRequest(BaseModel):
    course: str
    run: str
    revision: int
    base_revision: int


class ApprovalRequest(BaseModel):
    course: str
    run: str
    topic: str
    action: ApprovalAction


class RenderRequest(BaseModel):
    course: str
    run: str
    revision: int
    formats: list[RenderFormat]


class SuggestRequest(BaseModel):
    course: str
    run: str
    suggestion: SuggestionRequest


class SuggestionActionRequest(BaseModel):
    """Apply (with the base revision the reviewer saw) or reject one suggestion."""

    course: str
    run: str
    suggestion: str
    base_revision: int | None = None


class VerifyTopicRequest(BaseModel):
    course: str
    run: str
    topic: str
    base_revision: int
