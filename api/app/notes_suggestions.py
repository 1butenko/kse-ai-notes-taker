"""AI suggestions and manual verification jobs: models and their persistence.

Both live beside the revisions (notes/<run>/suggestions, notes/<run>/verification-jobs),
never inside a snapshot: a proposal or a check is not part of the notes until a commit
says so. The worker is the only writer; the API reads.
"""

import hashlib
import json
import re
from pathlib import Path
from time import time_ns
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field

from app.note_quality import changed_block_ids, changed_source_issues, substantive
from app.note_verification_identity import fingerprint
from app.notes import NoteBlock, NotesDocument, Verification, VerificationIssue
from app.notes_artifacts import atomic_json
from app.notes_revisions import (
    RevisionConflict,
    RevisionNotFound,
    RevisionStore,
    authored,
    find_topic,
)

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
    # True only for a clean check of the exact candidate: no major issue, no escalation,
    # and no standing evidence gap in the topic (those are listed in `blocking`).
    verified: bool = False
    blocking: list[VerificationIssue] = []
    # Source-support findings in changed blocks, derived again from stored checks for
    # pre-policy ready records rather than trusting their old `verified` flag.
    unsafe_citations: list[VerificationIssue] = []
    applied_revision: int | None = None
    # Read-time hint for the revision observed by the API. Apply checks again under lock.
    current_revision: int | None = None
    compatible: bool = False


class Insertion(BaseModel):
    """A new block placed after an existing one (None: first in the topic, whole-topic only)."""

    after_block_id: str | None
    block: NoteBlock


class SuggestionRecord(NoteSuggestion):
    """What is stored: the public view plus the privately kept scope and operations."""

    replacements: list[NoteBlock] = []
    insertions: list[Insertion] = []
    fingerprint: str | None = None
    # A conservative identity of the whole authored document and saved plan. Older
    # records are checked against immutable snapshots and the exact fingerprint.
    compatibility_digest: str | None = None

    def public(
        self,
        current_revision: int | None = None,
        compatible: bool = False,
        base_blocks: list[NoteBlock] | None = None,
    ) -> NoteSuggestion:
        changed = (
            changed_block_ids(base_blocks, self.proposed_blocks)
            if base_blocks is not None
            else {b.id for b in self.replacements} | {i.block.id for i in self.insertions}
        )
        unsafe = changed_source_issues(self.verification, self.proposed_blocks, changed)
        return NoteSuggestion.model_validate(
            self.model_dump(include=set(NoteSuggestion.model_fields))
            | {
                "current_revision": current_revision,
                "compatible": compatible,
                "unsafe_citations": unsafe,
                "verified": self.verified
                and not self.blocking
                and self.verification is not None
                and self.verification.passed
                and not self.verification.escalate
                and not any(substantive(issue) for issue in self.verification.issues),
            }
        )


def authored_document(document: NotesDocument) -> dict:
    """All substantive document fields, excluding per-topic verification results."""
    content = document.model_dump(mode="json")
    for section, saved in zip(document.sections, content["sections"], strict=True):
        saved["topics"] = [
            authored(topic) | {"topic_id": topic.topic_id} for topic in section.topics
        ]
    return content


def compatibility_digest(directory: Path, document: NotesDocument) -> str:
    """Conservative new-record identity: authored content plus raw saved plan bytes."""
    plan = directory / "plan.json"
    material = {
        "document": authored_document(document),
        "plan": plan.read_bytes().hex() if plan.is_file() else None,
    }
    return hashlib.sha256(
        json.dumps(material, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def compatible_revision(store: RevisionStore, record: SuggestionRecord, head: int) -> bool:
    """The stored checked candidate matches HEAD; only metadata-only chains may advance it.

    The public API calls this as a hint; Apply calls it again under the run lock and
    separately validates the exact candidate, scope and verifier fingerprint.
    """
    if head < record.base_revision or not record.fingerprint or record.verification is None:
        return False
    try:
        # A malformed frozen baseline must not become a positive public hint.
        store._baseline()
        if head != record.base_revision:
            history = store.history()
            base = next(
                i for i, item in enumerate(history) if item.revision == record.base_revision
            )
            chain = history[:base]
            if not chain or any(
                item.origin != "verification" or not item.verification_job for item in chain
            ):
                return False
            original = authored_document(store.read(record.base_revision).document)
            if any(
                authored_document(store.read(item.revision).document) != original for item in chain
            ):
                return False
        current = store.read(head).document
        if (
            record.compatibility_digest
            and compatibility_digest(store.directory, current) != record.compatibility_digest
        ):
            return False
        note = find_topic(current, record.topic_id)
        if note is None:
            return False
        candidate = note.model_copy(update={"blocks": record.proposed_blocks}, deep=True)
        return fingerprint(store.directory, current, candidate) == record.fingerprint
    except (OSError, ValueError, RevisionConflict, RevisionNotFound, StopIteration):
        return False


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
    # Standing evidence gaps that keep the topic from being verified by any check.
    blocking: list[VerificationIssue] = []
    # The metadata revision that recorded the result, if the base was still current.
    revision: int | None = None
    conflict: bool = False
    error: str | None = None
    fingerprint: str | None = None
    refresh_note: str | None = None


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
    atomic_json(
        _file(directory, SUGGESTIONS, record.id),
        record.model_dump(exclude={"current_revision", "compatible"}),
    )


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
