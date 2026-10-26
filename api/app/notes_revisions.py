"""Immutable notes snapshots. Only HEAD's parent chain is committed history.

The original notes.json is never rewritten and is revision 0. The first worker write
freezes it (with any recovered legacy language) as revisions/000000. Each later
revision is a complete directory renamed into place, then committed by replacing
head.json. Renames establish visibility only; there is no power-loss durability claim.

Read methods never write. Writers (worker only) hold the stable run lock, which
generation/resume admission shares; async callers acquire it in a thread.
"""

import fcntl
import json
import os
import shutil
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator

from app.note_approval import approval_fingerprint, is_teacher_approved
from app.note_assets import ASSET_PATH, image_references, load_asset
from app.note_structure import evidence_gaps, structure_gaps
from app.notes import (
    NoteBlock,
    NotesDocument,
    NotesRun,
    RenderFormat,
    TeacherDecision,
    TopicNote,
    load_document,
    now,
)


class RevisionInfo(BaseModel):
    revision: int
    parent: int | None
    created_at: str
    origin: Literal[
        "generation",
        "manual",
        "restore",
        "ai",
        "verification",
        "teacher_approval",
        "teacher_revocation",
    ]
    changed_topics: list[str]
    restored_from: int | None = None
    # Provenance, staged with the revision so a crash after HEAD can be reconciled.
    suggestion: str | None = None
    verification_job: str | None = None
    teacher_topic: str | None = None
    teacher_decision: TeacherDecision | None = None


class RevisionView(BaseModel):
    info: RevisionInfo
    document: NotesDocument


class TopicPatch(BaseModel):
    """A topic's complete new block order. An empty block ID asks for a new block."""

    base_revision: int = Field(ge=0)
    blocks: list[NoteBlock]
    # Only fills an unknown document language; it never translates or switches it.
    language: Literal["uk", "en"] | None = None


class ApprovalAction(BaseModel):
    base_revision: int = Field(ge=0)
    action: Literal["approve", "revoke"]
    reviewer: str = Field(min_length=1, max_length=120)
    comment: str | None = Field(default=None, max_length=2000)

    @field_validator("reviewer", mode="before")
    @classmethod
    def valid_reviewer(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        clean = value.strip()
        if not clean:
            raise ValueError("Reviewer name is required")
        return clean

    @field_validator("comment", mode="before")
    @classmethod
    def clean_comment(cls, value: object) -> object:
        return value.strip() or None if isinstance(value, str) else value


class RenderJob(BaseModel):
    id: str
    revision: int
    status: Literal["queued", "running", "done", "failed"]
    formats: list[RenderFormat]
    errors: list[str]


class EditResult(BaseModel):
    revision: RevisionInfo
    render: RenderJob | None = None


class RevisionConflict(Exception):
    """HTTP 409: a stale base, a run that cannot be edited, or stored state left untouched."""


class RevisionNotFound(Exception):
    """HTTP 404: an unknown run, topic or committed revision."""


class InvalidEdit(ValueError):
    """HTTP 422: block IDs, evidence, figures or language outside the edited scope."""


@contextmanager
def run_lock(directory: Path) -> Iterator[None]:
    """Blocking and never held across awaits. Never replace or delete this file."""
    with (directory / ".run.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def invalidate_verification(topic: TopicNote) -> None:
    """Changed content needs a fresh check: for manual, restored and AI edits alike."""
    topic.status = "unresolved"
    topic.verification_stale = True
    topic.verifier = None
    topic.rounds = 0
    topic.error = None
    # Verifier results (block-indexed or topic-level) described other text. What stays is
    # what the frozen evidence and the saved text themselves show.
    topic.open_issues = [*evidence_gaps(topic), *structure_gaps(topic)]


def authored(topic: TopicNote) -> dict:
    """What a revision changes; verification metadata is excluded."""
    return topic.model_dump(include={"title", "objectives", "blocks", "evidence"})


def find_topic(document: NotesDocument, topic_id: str) -> TopicNote | None:
    return next((t for s in document.sections for t in s.topics if t.topic_id == topic_id), None)


def patched_blocks(topic: TopicNote, blocks: list[NoteBlock]) -> list[NoteBlock]:
    """Kept IDs must be the topic's own and cite only its frozen evidence."""
    owned = {block.id for block in topic.blocks}
    evidence = {item.chunk_id for item in topic.evidence}
    kept: set[str] = set()
    result = []
    for block in blocks:
        block = block.model_copy(deep=True)
        if not block.id:
            block.id = f"b-{uuid4().hex}"
        elif block.id not in owned:
            raise InvalidEdit(f"Block {block.id} does not belong to topic {topic.topic_id}")
        elif block.id in kept:
            raise InvalidEdit(f"Block {block.id} appears more than once")
        else:
            kept.add(block.id)
        unknown = sorted(set(block.citations) - evidence)
        if unknown:
            raise InvalidEdit(
                f"Block {block.id} cites evidence outside topic {topic.topic_id}: "
                + ", ".join(unknown)
            )
        result.append(block)
    return result


def register_figures(directory: Path, document: NotesDocument, topics: list[TopicNote]) -> None:
    """Changed topics may show only images imported into this run's immutable catalog."""
    registered = {asset.path for asset in document.assets}
    for topic in topics:
        for block in topic.blocks:
            try:
                figures = image_references(block.content)
            except ValueError as error:
                raise InvalidEdit(f"Block {block.id}: {error}") from error
            for _, path, _ in figures:
                if path in registered:
                    continue
                try:
                    asset = load_asset(directory, ASSET_PATH.fullmatch(path)[1])
                except (OSError, ValueError) as error:
                    raise InvalidEdit(f"Unknown note asset: {path}") from error
                if asset.path != path:
                    raise InvalidEdit(f"Unknown note asset: {path}")
                document.assets.append(asset)
                registered.add(path)


class RevisionStore:
    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.revisions = directory / "revisions"
        self.head = directory / "head.json"
        # The render job the last commit through this instance staged inside its revision.
        self.staged: RenderJob | None = None

    # Reading. A view reads HEAD once, then only immutable snapshots.

    def _folder(self, revision: int) -> Path:
        return self.revisions / f"{revision:06d}"

    def _head(self) -> int:
        return json.loads(self.head.read_text())["revision"] if self.head.is_file() else 0

    def _info(self, revision: int) -> RevisionInfo:
        return RevisionInfo.model_validate_json(
            (self._folder(revision) / "revision.json").read_text()
        )

    def _load(self, revision: int) -> RevisionView:
        document = (self._folder(revision) / "document.json").read_text()
        return RevisionView(
            info=self._info(revision), document=NotesDocument.model_validate_json(document)
        )

    def _original(self) -> RevisionView:
        """Revision 0 as notes.json presents it, with the read-only legacy language fallback."""
        document = load_document(self.directory.parent.parent, self.directory.name)
        if document is None:
            raise RevisionNotFound("Notes document not found")
        info = RevisionInfo(
            revision=0,
            parent=None,
            created_at=document.created_at,
            origin="generation",
            changed_topics=[],
        )
        return RevisionView(info=info, document=document)

    def _baseline(self) -> RevisionView | None:
        """The materialized revision 0, or None before the first write. Never repaired."""
        if not self._folder(0).exists():
            return None
        original = self._original()
        try:
            baseline = self._load(0)
            saved = NotesDocument.model_validate_json((self.directory / "notes.json").read_text())
        except (OSError, ValueError) as error:
            raise RevisionConflict("Stored revision 0 is unreadable; it was left as is") from error
        # Only an unknown saved language may have been frozen from the legacy fallback.
        unfrozen = baseline.document.model_copy(update={"language": original.document.language})
        if (
            baseline.info != original.info
            or unfrozen != original.document
            or saved.language not in (None, baseline.document.language)
        ):
            raise RevisionConflict("Stored revision 0 does not match notes.json; it was left as is")
        return baseline

    def _zero(self) -> RevisionView:
        try:
            baseline = self._baseline()
        except RevisionConflict:
            baseline = None  # Writers refuse it; readers keep serving notes.json.
        return baseline or self._original()

    def _view(self, revision: int) -> RevisionView:
        return self._zero() if revision == 0 else self._load(revision)

    def _history(self) -> Iterator[RevisionInfo]:
        """HEAD and its parents. Uncommitted (orphan) directories never appear."""
        revision = self._head()
        while True:
            info = self._zero().info if revision == 0 else self._info(revision)
            if info.revision != revision or (info.parent is not None and info.parent >= revision):
                raise ValueError(f"Corrupt revision history at {revision}")
            yield info
            if info.parent is None:
                return
            revision = info.parent

    def current(self) -> RevisionView:
        return self._view(self._head())

    def read(self, revision: int) -> RevisionView:
        if any(info.revision == revision for info in self._history()):
            return self._view(revision)
        raise RevisionNotFound("Revision not found")

    # Writing, under the run lock: check, then publish a snapshot, then replace HEAD.

    @contextmanager
    def locked(self) -> Iterator[None]:
        """The run lock, for a completed run only. Short: never held across awaits."""
        metadata = self.directory / "run.json"
        if not metadata.is_file():
            raise RevisionNotFound("Notes run not found")
        with run_lock(self.directory):
            if NotesRun.model_validate_json(metadata.read_text()).status != "done":
                raise RevisionConflict("Only completed notes runs can be edited")
            self.staged = None
            yield

    def head_revision(self) -> int:
        return self._head()

    def history(self) -> "list[RevisionInfo]":
        """Newest first: HEAD and its parents."""
        return [*self._history()]

    @contextmanager
    def transaction(self, base: int) -> Iterator[RevisionView]:
        """The current revision, if this completed run is still at `base`."""
        with self.locked():
            head = self._head()
            if base != head:
                raise RevisionConflict(f"Revision changed; current revision is {head}")
            yield (self._baseline() or self._original()) if head == 0 else self._load(head)

    def _publish(self, view: RevisionView) -> RenderJob | None:
        """Write under a unique staging name, then rename the complete directory into place."""
        self.revisions.mkdir(exist_ok=True)
        stage = self.revisions / f".staging-{uuid4().hex}"
        stage.mkdir()
        try:
            (stage / "document.json").write_text(view.document.model_dump_json(indent=2))
            (stage / "revision.json").write_text(view.info.model_dump_json(indent=2))
            (stage / "artifacts").mkdir()
            job = None
            if view.info.revision > 0:
                # Intent is staged before HEAD, even if scheduling never happens.
                from app.notes_artifacts import new_job

                job = new_job(view.info.revision, ["html", "pdf"])
                (stage / "jobs").mkdir()
                (stage / "jobs" / f"{job.id}.json").write_text(job.model_dump_json())
            # The run lock and allocation policy ensure the destination never exists.
            os.rename(stage, self._folder(view.info.revision))
        finally:
            if stage.exists():
                shutil.rmtree(stage)
        return job

    def _allocate(self) -> int:
        """Above every numbered directory, orphans included: gaps are fine, reuse is not."""
        names = [p.name for p in self.revisions.iterdir()]
        used = [int(name) for name in names if name.isascii() and name.isdigit()]
        return max(used, default=0) + 1

    def commit(
        self,
        current: RevisionView,
        document: NotesDocument,
        origin: Literal[
            "manual", "restore", "ai", "verification", "teacher_approval", "teacher_revocation"
        ],
        changed: list[str],
        restored_from: int | None = None,
        suggestion: str | None = None,
        verification_job: str | None = None,
        teacher_topic: str | None = None,
        teacher_decision: TeacherDecision | None = None,
    ) -> RevisionView:
        """Publish `document` as the next revision. Call inside `transaction`/`locked`."""
        if self._baseline() is None:
            self._publish(current if current.info.revision == 0 else self._original())
        # All mutation paths converge here. Only this transaction may introduce a
        # decision; other commits inherit the current one while its identity matches.
        for section in document.sections:
            for topic in section.topics:
                previous = find_topic(current.document, topic.topic_id)
                if teacher_topic == topic.topic_id and teacher_decision is not None:
                    topic.teacher_decision = teacher_decision
                elif previous and approval_fingerprint(
                    current.document, previous
                ) == approval_fingerprint(document, topic):
                    topic.teacher_decision = previous.teacher_decision
                else:
                    topic.teacher_decision = None
                if (
                    topic.teacher_decision
                    and topic.teacher_decision.decision == "approved"
                    and not is_teacher_approved(document, topic)
                ):
                    topic.teacher_decision = None
        view = RevisionView(
            info=RevisionInfo(
                revision=self._allocate(),
                parent=current.info.revision,
                created_at=now(),
                origin=origin,
                changed_topics=changed,
                restored_from=restored_from,
                suggestion=suggestion,
                verification_job=verification_job,
                teacher_topic=teacher_topic,
                teacher_decision=teacher_decision,
            ),
            document=document,
        )
        self.staged = self._publish(view)
        temporary = self.directory / f".head-{uuid4().hex}"
        try:
            temporary.write_text(json.dumps({"revision": view.info.revision}))
            os.replace(temporary, self.head)  # Sole editorial commit point.
        finally:
            temporary.unlink(missing_ok=True)
        return view

    def commit_topic(
        self, topic_id: str, patch: TopicPatch, origin: Literal["manual", "ai"] = "manual"
    ) -> RevisionView:
        with self.transaction(patch.base_revision) as current:
            document = current.document.model_copy(deep=True)
            topic = find_topic(document, topic_id)
            if topic is None:
                raise RevisionNotFound("Topic not found")
            blocks = patched_blocks(topic, patch.blocks)
            edited = blocks != topic.blocks
            language = patch.language not in (None, document.language)
            if language and document.language is not None:
                raise InvalidEdit(
                    f"The notes are in {document.language}; changing the language is not supported"
                )
            if not edited and not language:
                return current  # Nothing changed: no revision, so nothing to render.
            if language:
                # A metadata revision: topic content and verification stay as they are.
                document.language = patch.language
            if edited:
                topic.blocks = blocks
                invalidate_verification(topic)
                register_figures(self.directory, document, [topic])
            return self.commit(current, document, origin, [topic_id] if edited else [])

    def restore(self, target_revision: int, base_revision: int) -> RevisionView:
        """Copy a committed revision's content into a new revision; HEAD never moves back."""
        with self.transaction(base_revision) as current:
            target = self.read(target_revision).document
            document = current.document.model_copy(deep=True)
            restored: list[TopicNote] = []
            for section in document.sections:
                for index, topic in enumerate(section.topics):
                    old = find_topic(target, topic.topic_id)
                    if old is None or authored(old) == authored(topic):
                        continue  # Unchanged content keeps its *current* verification.
                    copy = old.model_copy(deep=True)
                    invalidate_verification(copy)
                    section.topics[index] = copy
                    restored.append(copy)
            if not restored:
                return current
            register_figures(self.directory, document, restored)
            return self.commit(
                current,
                document,
                "restore",
                [topic.topic_id for topic in restored],
                restored_from=target_revision,
            )

    def decide(self, topic_id: str, action: ApprovalAction) -> RevisionView:
        with self.transaction(action.base_revision) as current:
            document = current.document.model_copy(deep=True)
            topic = find_topic(document, topic_id)
            if topic is None:
                raise RevisionNotFound("Topic not found")
            valid = approval_fingerprint(document, topic)
            if action.action == "approve":
                if valid is None:
                    raise InvalidEdit(
                        "Only a saved, nonempty topic with registered evidence "
                        "and assets can be approved"
                    )
                if is_teacher_approved(document, topic):
                    raise InvalidEdit("This topic is already approved")
            elif not is_teacher_approved(document, topic):
                raise InvalidEdit("This topic has no active approval to revoke")
            decision = TeacherDecision(
                decision="approved" if action.action == "approve" else "revoked",
                reviewer=action.reviewer,
                at=now(),
                comment=action.comment,
                fingerprint=valid if action.action == "approve" else None,
            )
            return self.commit(
                current,
                document,
                "teacher_approval" if action.action == "approve" else "teacher_revocation",
                [],
                teacher_topic=topic_id,
                teacher_decision=decision,
            )

    # Last: inside the class body this name shadows the builtin used in annotations above.
    def list(self) -> "list[RevisionInfo]":
        return [*reversed([*self._history()])]
