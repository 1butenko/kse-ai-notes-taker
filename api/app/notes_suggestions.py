"""AI suggestions and manual verification jobs: models and their persistence.

Both live beside the revisions (notes/<run>/suggestions, notes/<run>/verification-jobs),
never inside a snapshot: a proposal or a check is not part of the notes until a commit
says so. The worker is the only writer; the API reads.
"""

import re
from pathlib import Path
from time import time_ns
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field

from app.notes import NoteBlock, Verification
from app.notes_artifacts import atomic_json
from app.notes_revisions import RevisionNotFound

SUGGESTIONS = "suggestions"
VERIFICATIONS = "verification-jobs"
IDENTIFIER = re.compile(r"[0-9]+-[0-9a-f]{32}\Z")
MAX_INSTRUCTION = 2000

type SuggestionStatus = Literal["queued", "running", "ready", "failed", "applied", "rejected"]


class SuggestionRequest(BaseModel):
    base_revision: int = Field(ge=0)
    topic_id: str
    # Empty means the whole topic. Other topics are never in scope.
    block_ids: list[str] = []
    instruction: str = Field(max_length=MAX_INSTRUCTION)


class NoteSuggestion(BaseModel):
    id: str
    base_revision: int
    topic_id: str
    status: SuggestionStatus
    # The complete assembled topic (all blocks, final order and IDs), not only the changes.
    proposed_blocks: list[NoteBlock] = []
    # The fresh check of exactly proposed_blocks.
    verification: Verification | None = None
    error: str | None = None
    block_ids: list[str] = []
    instruction: str = ""
    # True only for a clean check of the exact candidate: no major issue, no escalation.
    verified: bool = False
    applied_revision: int | None = None


class Insertion(BaseModel):
    """A new block placed after an existing one (None: first in the topic, whole-topic only)."""

    after_block_id: str | None
    block: NoteBlock


class SuggestionRecord(NoteSuggestion):
    """What is stored: the public view plus the privately kept scope and operations."""

    replacements: list[NoteBlock] = []
    insertions: list[Insertion] = []
    fingerprint: str | None = None

    def public(self) -> NoteSuggestion:
        return NoteSuggestion.model_validate(
            self.model_dump(include=set(NoteSuggestion.model_fields))
        )


class VerifyBody(BaseModel):
    base_revision: int = Field(ge=0)


class VerificationJob(BaseModel):
    id: str
    topic_id: str
    base_revision: int
    status: Literal["queued", "running", "done", "failed"]
    # The check of the frozen base topic; kept even when it could not be recorded.
    verification: Verification | None = None
    verified: bool = False
    # The metadata revision that recorded the result, if the base was still current.
    revision: int | None = None
    conflict: bool = False
    error: str | None = None
    fingerprint: str | None = None


def new_id() -> str:
    return f"{time_ns()}-{uuid4().hex}"


def _file(directory: Path, kind: str, identifier: str) -> Path:
    if not IDENTIFIER.fullmatch(identifier):
        raise RevisionNotFound("Not found")
    return directory / kind / f"{identifier}.json"


def read_suggestion(directory: Path, identifier: str) -> SuggestionRecord:
    path = _file(directory, SUGGESTIONS, identifier)
    if not path.is_file():
        raise RevisionNotFound("Suggestion not found")
    record = SuggestionRecord.model_validate_json(path.read_text())
    if record.id != identifier:
        raise RevisionNotFound("Suggestion not found")
    return record


def write_suggestion(directory: Path, record: SuggestionRecord) -> None:
    atomic_json(_file(directory, SUGGESTIONS, record.id), record.model_dump())


def read_verification_job(directory: Path, identifier: str) -> VerificationJob:
    path = _file(directory, VERIFICATIONS, identifier)
    if not path.is_file():
        raise RevisionNotFound("Verification job not found")
    job = VerificationJob.model_validate_json(path.read_text())
    if job.id != identifier:
        raise RevisionNotFound("Verification job not found")
    return job


def write_verification_job(directory: Path, job: VerificationJob) -> None:
    atomic_json(_file(directory, VERIFICATIONS, job.id), job.model_dump())


def stored[T: BaseModel](directory: Path, kind: str, model: type[T]) -> list[T]:
    """Every readable record of one kind; a malformed file is skipped, never fatal."""
    records = []
    for path in sorted((directory / kind).glob("*.json")):
        try:
            record = model.model_validate_json(path.read_text())
        except (OSError, ValueError):
            print(f"Skipping unreadable record {path}")
            continue
        if path.stem == getattr(record, "id", None):
            records.append(record)
    return records
