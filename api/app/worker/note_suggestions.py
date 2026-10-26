"""Targeted AI suggestions and manual rechecks for saved note topics.

A suggestion is a proposal stored beside the revisions, with the server-assembled
candidate topic and a fresh check of exactly that candidate. Nothing changes the notes
until Apply commits it as a revision (origin "ai"). A recheck verifies a frozen topic
and, if its revision is still current, records the result as a metadata revision
(origin "verification"). Both are jobs: persisted before they are scheduled, finished
under short run-lock sections (never across model calls) and failed on restart.
"""

import asyncio
import hashlib
from collections.abc import Callable
from pathlib import Path
from uuid import uuid4

from app.note_quality import changed_block_ids, changed_source_issues, normalized
from app.note_structure import evidence_gap, evidence_gaps, structure_gaps
from app.note_verification_identity import draft_of, fingerprint, verification_inputs
from app.notes import (
    BlockKind,
    CoursePlan,
    Inputs,
    NoteBlock,
    NotesDocument,
    TopicNote,
    Verification,
)
from app.notes_revisions import (
    EditResult,
    InvalidEdit,
    RenderJob,
    RevisionConflict,
    RevisionInfo,
    RevisionNotFound,
    RevisionStore,
    RevisionView,
    find_topic,
    invalidate_verification,
    register_figures,
    run_lock,
)
from app.notes_suggestions import (
    SUGGESTIONS,
    VERIFICATIONS,
    Insertion,
    SuggestionRecord,
    SuggestionRequest,
    VerificationJob,
    compatibility_digest,
    compatible_revision,
    new_id,
    read_suggestion,
    read_verification_job,
    stored,
    write_suggestion,
    write_verification_job,
)
from app.schemas import Strict
from app.storage import sha256
from app.worker.config import WorkerSettings
from app.worker.llm import ask, chat
from app.worker.models import NotesModels
from app.worker.notes import GenerationProvenance, input_fingerprint, inputs_digest
from app.worker.openrouter import Opener, OpenRouterClient
from app.worker.references import validate_references
from app.worker.revisions import guarded, render_revision
from app.worker.sources import Retriever, session_materials
from app.worker.topics import (
    context_text,
    evidence_text,
    is_clean,
    page_of,
    registry_text,
    select_evidence,
    topic_text,
    verification_issues,
    verify,
)

INTERRUPTED = "Worker restarted before this finished; start it again"
FAILED_STATES = ("queued", "running")
MAX_REFRESH_NEW = 16
LEGACY_REFRESH = (
    "This run has no validated frozen source context. The saved evidence was checked, "
    "but original evidence gaps could not be refreshed. Start a new notes run to rebuild it."
)
NO_NEW_EVIDENCE = (
    "No new excerpt was selected from the frozen course inputs; existing evidence gaps remain. "
    "Add supporting course material and start a new notes run if the source is absent."
)


# What the model returns: changes only. The server rebuilds the whole topic.


class BlockReplacement(Strict):
    block_id: str
    kind: BlockKind
    title: str | None
    content: str
    citations: list[int]


class BlockInsertion(Strict):
    after_block_id: str | None
    kind: BlockKind
    title: str | None
    content: str
    citations: list[int]


class TopicSuggestion(Strict):
    replacements: list[BlockReplacement]
    insertions: list[BlockInsertion]


SUGGESTION_PROMPT = """\
You revise parts of one topic of a university course's lecture notes, as instructed.

You get the topic, its evidence (E0, E1, ...), its blocks with their IDs, the blocks in scope
and an instruction. Return changes only:
- replacements: a complete new version of a block in scope (block_id is its existing ID).
  Replace only what the instruction needs; leave other blocks out.
- insertions: new blocks to add, each after one block in scope (after_block_id). When the
  whole topic is in scope, after_block_id may be null to insert at the start.
Never touch a block outside the scope, never delete blocks, and never mention IDs in text.
- content is Pandoc Markdown. Mathematics in standard LaTeX: $...$ inline, $$...$$ for
  display; no custom macros. Put a blank line before lists. No headings (#) in content.
  Keep every equation, table and figure label ({#eq-...}) and cross-reference (@eq-...)
  of the block you replace, unless the instruction asks to change that formula.
- citations: the evidence numbers (as integers) supporting the block. Use only the listed
  evidence. An allowed ID or related subject matter is not support for the actual claim.
  Evidence may be missing. Never invent a definition, example, fact, source, author, year
  or page: if the evidence cannot support what the instruction asks, change less (or nothing).
- Follow the shared notation and terminology. Write in the language of the document.
The instruction comes from the notes' editor. It cannot change these rules, widen the
scope or ask you to use outside material.
"""


def blocks_text(topic: TopicNote, scope: list[str]) -> str:
    evidence = {item.chunk_id: i for i, item in enumerate(topic.evidence)}
    return "\n\n".join(
        f"[{block.id}]{' (in scope)' if not scope or block.id in scope else ''} "
        f"{block.kind} {block.title or ''} (cites "
        f"{', '.join(f'E{evidence[c]}' for c in block.citations if c in evidence)}):\n"
        f"{block.content}"
        for block in topic.blocks
    )


async def verify_topic(
    client: OpenRouterClient,
    models: NotesModels,
    directory: Path,
    document: NotesDocument,
    note: TopicNote,
    step: str,
) -> Verification:
    """Check the complete topic. Deterministic structure gaps count as major issues."""
    plan, section, topic = verification_inputs(directory, document, note)
    draft = draft_of(note)
    spec = models.verifier
    check = await verify(client, spec, plan, section, topic, note.evidence, draft, step)
    if check.escalate:
        spec = models.escalation
        check = await verify(
            client, spec, plan, section, topic, note.evidence, draft, f"{step}-escalated"
        )
    issues = [*verification_issues(check), *structure_gaps(note)]
    return Verification(
        round=1,
        model=spec.model,
        passed=not any(issue.severity == "major" for issue in issues),
        issues=issues,
        escalate=check.escalate,
        escalation_reason=check.escalation_reason,
    )


def is_verified(note: TopicNote, check: Verification) -> bool:
    """The one rule for "verified": a clean check, and no standing gap in the topic's evidence
    (what blocks it is `evidence_gaps(note)`; certify and every public flag use this)."""
    return is_clean(check) and not evidence_gaps(note)


def certify(note: TopicNote, check: Verification) -> None:
    """Record a completed check of this exact content. Only a clean check verifies it."""
    note.open_issues = [
        *evidence_gaps(note),
        *[issue for issue in normalized(check.issues) if issue.severity == "major"],
    ]
    note.verifier = check.model
    note.rounds = check.round
    note.verification_stale = False
    note.error = None
    note.status = "verified" if is_verified(note, check) and not note.open_issues else "unresolved"


# Candidate assembly: pure, deterministic, and run again at apply.


def assemble(
    note: TopicNote,
    scope: list[str],
    replacements: list[NoteBlock],
    insertions: list[Insertion],
) -> list[NoteBlock]:
    """The topic's full new block list. Unselected blocks and their order are untouched."""
    owned = [block.id for block in note.blocks]
    allowed = set(scope) if scope else set(owned)
    if not allowed <= set(owned):
        raise InvalidEdit("The selection contains blocks outside this topic")
    evidence = {item.chunk_id for item in note.evidence}
    replaced: dict[str, NoteBlock] = {}
    for block in replacements:
        if block.id not in allowed:
            raise InvalidEdit(f"Block {block.id} is outside the selected blocks")
        if block.id in replaced:
            raise InvalidEdit(f"Block {block.id} is replaced more than once")
        replaced[block.id] = block
    added: dict[str | None, list[NoteBlock]] = {}
    seen = set(owned)
    for insertion in insertions:
        anchor = insertion.after_block_id
        if anchor is None and scope:
            raise InvalidEdit("New blocks must follow a selected block")
        if anchor is not None and anchor not in allowed:
            raise InvalidEdit(f"New blocks cannot follow {anchor}: it is not selected")
        if insertion.block.id in seen:
            raise InvalidEdit(f"Block {insertion.block.id} appears more than once")
        seen.add(insertion.block.id)
        added.setdefault(anchor, []).append(insertion.block)
    for block in [*replaced.values(), *(i.block for i in insertions)]:
        if not block.content.strip():
            raise InvalidEdit(f"Block {block.id} has no text")
        foreign = sorted(set(block.citations) - evidence)
        if foreign:
            raise InvalidEdit(
                f"Block {block.id} cites evidence outside topic {note.topic_id}: "
                + ", ".join(foreign)
            )
    result = [*added.get(None, [])]
    for block in note.blocks:
        result.append(replaced.get(block.id, block))
        result.extend(added.get(block.id, []))
    if result == note.blocks:
        raise InvalidEdit("The suggestion changes nothing")
    return result


def convert(
    note: TopicNote, suggestion: TopicSuggestion
) -> tuple[list[NoteBlock], list[Insertion]]:
    """The model's evidence numbers become chunk IDs; the server assigns every new ID."""

    def chunks(numbers: list[int], where: str) -> list[str]:
        for number in numbers:
            if not 0 <= number < len(note.evidence):
                raise InvalidEdit(f"{where} cites unknown evidence E{number}")
        return list(dict.fromkeys(note.evidence[n].chunk_id for n in numbers))

    replacements = [
        NoteBlock(
            id=item.block_id,
            kind=item.kind,
            title=item.title,
            content=item.content,
            citations=chunks(item.citations, f"Block {item.block_id}"),
        )
        for item in suggestion.replacements
    ]
    insertions = [
        Insertion(
            after_block_id=item.after_block_id,
            block=NoteBlock(
                id=f"b-{uuid4().hex}",
                kind=item.kind,
                title=item.title,
                content=item.content,
                citations=chunks(item.citations, "A new block"),
            ),
        )
        for item in suggestion.insertions
    ]
    return replacements, insertions


def check_candidate(
    directory: Path, document: NotesDocument, topic_id: str, blocks: list[NoteBlock]
) -> None:
    """The candidate may not break figures or cross-references of the current notes."""
    candidate = document.model_copy(deep=True)
    target = find_topic(candidate, topic_id)
    assert target is not None
    before = set(validate_references(candidate))
    target.blocks = blocks
    register_figures(directory, candidate, [target])
    introduced = sorted(set(validate_references(candidate)) - before)
    if introduced:
        raise InvalidEdit("The suggestion breaks references: " + "; ".join(introduced))


# Guarded record transitions: one outcome per race, under a short run lock.


def transition(
    directory: Path,
    identifier: str,
    allowed: tuple[str, ...],
    change: Callable[[SuggestionRecord], None],
) -> SuggestionRecord | None:
    """Apply `change` if the suggestion is still in an allowed state; else None."""
    with run_lock(directory):
        record = read_suggestion(directory, identifier)
        if record.status not in allowed:
            return None
        change(record)
        write_suggestion(directory, record)
        return record


def create_suggestion(directory: Path, request: SuggestionRequest) -> SuggestionRecord:
    store = RevisionStore(directory)
    instruction = request.instruction.strip()
    if not instruction:
        raise InvalidEdit("Describe the change you want")
    with store.locked():
        head = store.head_revision()
        if request.base_revision != head:
            raise RevisionConflict(f"Revision changed; current revision is {head}")
        note = find_topic(store.current().document, request.topic_id)
        if note is None:
            raise RevisionNotFound("Topic not found")
        if not note.blocks or not note.evidence or note.status in ("no_evidence", "failed"):
            raise InvalidEdit("This topic has no text and evidence to revise")
        owned = {block.id for block in note.blocks}
        if len(set(request.block_ids)) != len(request.block_ids):
            raise InvalidEdit("A block is selected more than once")
        unknown = [b for b in request.block_ids if b not in owned]
        if unknown:
            raise InvalidEdit(f"Blocks outside topic {note.topic_id}: " + ", ".join(unknown))
        record = SuggestionRecord(
            id=new_id(),
            base_revision=head,
            topic_id=request.topic_id,
            status="queued",
            block_ids=list(request.block_ids),
            instruction=instruction,
        )
        write_suggestion(directory, record)
        return record


async def run_suggestion(
    directory: Path, identifier: str, settings: WorkerSettings, opener: Opener
) -> None:
    """Prepare the candidate and its check. Whatever happens, the record ends in a final state."""
    try:
        started = await asyncio.to_thread(
            transition, directory, identifier, ("queued",), set_status("running")
        )
        if started is None:  # Rejected before it began.
            return
        view = await asyncio.to_thread(RevisionStore(directory).read, started.base_revision)
        note = find_topic(view.document, started.topic_id)
        if note is None:
            raise RevisionNotFound("Topic not found")
        models = NotesModels.from_settings(settings)
        plan, section, planned = verification_inputs(directory, view.document, note)
        async with opener() as client:
            language = {"uk": "Ukrainian", "en": "English"}.get(view.document.language or "")
            answer = await ask(
                client,
                chat(
                    SUGGESTION_PROMPT,
                    f"Language: {language or 'the language of the topic'}",
                    topic_text(section, planned),
                    context_text(plan, planned),
                    registry_text(plan),
                    "Evidence:\n\n" + evidence_text(note.evidence),
                    "Blocks:\n\n" + blocks_text(note, started.block_ids),
                    "Selected block IDs: " + (", ".join(started.block_ids) or "(the whole topic)"),
                    "Instruction:\n" + started.instruction,
                ),
                TopicSuggestion,
                "topic_suggestion",
                step="suggest-blocks",
                spec=models.writer,
            )
            replacements, insertions = convert(note, answer)
            blocks = assemble(note, started.block_ids, replacements, insertions)
            await asyncio.to_thread(
                check_candidate, directory, view.document, note.topic_id, blocks
            )
            candidate = note.model_copy(update={"blocks": blocks}, deep=True)
            digest = fingerprint(directory, view.document, candidate)
            context_digest = compatibility_digest(directory, view.document)

            def assembled(record: SuggestionRecord) -> None:
                record.replacements, record.insertions = replacements, insertions
                record.proposed_blocks, record.fingerprint = blocks, digest
                record.compatibility_digest = context_digest

            # The exact candidate, with its assigned IDs, is kept before it is checked.
            kept = await asyncio.to_thread(
                transition, directory, identifier, ("running",), assembled
            )
            if kept is None:
                return
            check = await verify_topic(
                client, models, directory, view.document, candidate, "verify-suggestion"
            )

        def finished(record: SuggestionRecord) -> None:
            record.verification = check
            record.verified = is_verified(candidate, check)
            record.blocking = evidence_gaps(candidate)
            changed = changed_block_ids(note.blocks, blocks)
            unsupported = changed_source_issues(check, blocks, changed)
            if unsupported:
                record.status = "failed"
                record.error = (
                    "The proposed text cites evidence that does not support its claims: "
                    + "; ".join(
                        f"Block {i.block + 1 if i.block is not None else 'unknown'}: "
                        f"{i.detail} {i.fix}"
                        for i in unsupported
                    )
                    + " Refresh the topic's evidence with Verify this topic again, "
                    "or edit the text."
                )
            else:
                record.status = "ready"

        await asyncio.to_thread(transition, directory, identifier, ("running",), finished)
    except asyncio.CancelledError:
        await asyncio.shield(asyncio.to_thread(fail_suggestion, directory, identifier, INTERRUPTED))
        raise
    except Exception as error:
        message = str(getattr(error, "detail", None) or error) or type(error).__name__
        print(f"Suggestion {identifier} failed: {error!r}")
        await asyncio.to_thread(fail_suggestion, directory, identifier, message)


def set_status(status: str) -> Callable[[SuggestionRecord], None]:
    def change(record: SuggestionRecord) -> None:
        record.status = status  # type: ignore[assignment]

    return change


def fail_suggestion(directory: Path, identifier: str, message: str) -> None:
    def change(record: SuggestionRecord) -> None:
        record.status, record.error = "failed", message

    try:
        transition(directory, identifier, FAILED_STATES, change)
    except Exception as error:  # Nothing more to do; recovery reports it on restart.
        print(f"Suggestion {identifier} could not be marked failed: {error!r}")


def application_of(store: RevisionStore, key: str, value: str) -> RevisionInfo | None:
    """The committed revision that carries this provenance, if any."""
    return next((i for i in store.history() if getattr(i, key) == value), None)


def apply_suggestion(
    directory: Path, identifier: str, base_revision: int
) -> tuple[RevisionView, RevisionStore, bool]:
    """Commit a ready suggestion once. Returns (revision, store, created)."""
    store = RevisionStore(directory)
    with store.locked():
        record = read_suggestion(directory, identifier)
        existing = application_of(store, "suggestion", identifier)
        if existing is not None:  # Applied before (perhaps a crash left the record behind).
            if record.status != "applied":
                record.status, record.applied_revision = "applied", existing.revision
                write_suggestion(directory, record)
            return store.read(existing.revision), store, False
        if record.status != "ready":
            raise RevisionConflict(f"This suggestion is {record.status} and cannot be applied")
        base_note = find_topic(store.read(record.base_revision).document, record.topic_id)
        if base_note is None:
            raise RevisionConflict("The suggestion's base topic is unavailable")
        unsupported = changed_source_issues(
            record.verification,
            record.proposed_blocks,
            changed_block_ids(base_note.blocks, record.proposed_blocks),
        )
        if unsupported:
            raise InvalidEdit(
                "The checked suggestion has unsupported citations in changed blocks: "
                + "; ".join(f"{i.detail} {i.fix}" for i in unsupported)
                + " Refresh the evidence or request a different suggestion."
            )
        head = store.head_revision()
        if base_revision != record.base_revision or not compatible_revision(store, record, head):
            raise RevisionConflict(
                f"Revision changed; the suggestion is for revision {record.base_revision} "
                f"and the notes are at revision {head}"
            )
        current = store.current()
        note = find_topic(current.document, record.topic_id)
        if note is None:
            raise RevisionNotFound("Topic not found")
        blocks = assemble(note, record.block_ids, record.replacements, record.insertions)
        if blocks != record.proposed_blocks:
            raise RevisionConflict("The stored suggestion does not match its scope")
        check_candidate(directory, current.document, record.topic_id, blocks)
        document = current.document.model_copy(deep=True)
        target = find_topic(document, record.topic_id)
        assert target is not None
        target.blocks = blocks
        invalidate_verification(target)
        register_figures(directory, document, [target])
        candidate_matches = record.fingerprint == fingerprint(directory, document, target)
        if not candidate_matches:
            raise RevisionConflict("The checked candidate or its context changed")
        if record.verification is not None and candidate_matches:
            certify(target, record.verification)
        view = store.commit(current, document, "ai", [record.topic_id], suggestion=record.id)
        record.status, record.applied_revision = "applied", view.info.revision
        write_suggestion(directory, record)
        return view, store, True


def reject_suggestion(directory: Path, identifier: str) -> SuggestionRecord:
    store = RevisionStore(directory)
    with store.locked():
        record = read_suggestion(directory, identifier)
        if record.status == "applied" or application_of(store, "suggestion", identifier):
            raise RevisionConflict("This suggestion was already applied")
        if record.status != "rejected":
            record.status = "rejected"
            write_suggestion(directory, record)
        return record


async def apply(directory: Path, identifier: str, base_revision: int) -> tuple[EditResult, bool]:
    view, store, created = await guarded(
        lambda: apply_suggestion(directory, identifier, base_revision)
    )
    return EditResult(revision=view.info, render=store.staged if created else None), created


# Manual verification.


def _safe_saved_paths(directory: Path, provenance: GenerationProvenance, inputs: Inputs) -> None:
    """Reject traversal and symlinks before hashing any saved material path."""
    uploads = directory.parent.parent.parent.resolve()
    materials = [
        material.file for material, _ in session_materials(provenance.plan, provenance.transcript)
    ]
    if not {source.file for source in inputs.sources} <= set(materials):
        raise ValueError("Frozen source registry is not in the saved generation plan")
    paths = [*materials, *(source.file for source in inputs.sources)]
    course = directory.parent.parent.name
    for name in paths:
        path = Path(name)
        if path.is_absolute() or ".." in path.parts or not path.parts or path.parts[0] != course:
            raise ValueError("Frozen source path is outside the course uploads")
        target = uploads / path
        if not target.resolve().is_relative_to(uploads):
            raise ValueError("Frozen source path is outside the course uploads")
        part = uploads
        for component in path.parts:
            part = part / component
            if part.is_symlink():
                raise ValueError("Frozen source path uses a symlink")


def refresh_inputs(directory: Path, document: NotesDocument, note: TopicNote):
    """Validated immutable inventory for this run; None is a limited legacy fallback."""
    provenance_file = directory / "provenance.json"
    inputs_file = directory / "inputs.json"
    plan_file = directory / "plan.json"
    if not provenance_file.exists() and not inputs_file.exists():
        return None
    if any(path.is_symlink() for path in (provenance_file, inputs_file, plan_file)):
        raise InvalidEdit("Frozen source context uses a symlink; evidence was not changed")
    try:
        provenance = GenerationProvenance.model_validate_json(provenance_file.read_text())
        inputs = Inputs.model_validate_json(inputs_file.read_text())
        plan = CoursePlan.model_validate_json(plan_file.read_text())
    except (OSError, ValueError) as error:
        raise InvalidEdit(
            "Frozen source context is missing or corrupt; evidence was not changed"
        ) from error
    if provenance.version != 1:
        raise InvalidEdit("Frozen source provenance version is unsupported")
    try:
        _safe_saved_paths(directory, provenance, inputs)
        actual = input_fingerprint(directory.parent.parent, provenance.plan, provenance.transcript)
    except (OSError, ValueError) as error:
        raise InvalidEdit(
            "Frozen source provenance is unsafe or changed; evidence was not changed"
        ) from error
    if actual != provenance.fingerprint or inputs_digest(inputs) != provenance.inputs_sha256:
        raise InvalidEdit(
            "Frozen source provenance or input digest changed; evidence was not changed"
        )
    if [s.model_dump() for s in inputs.sources] != [s.model_dump() for s in document.sources]:
        raise InvalidEdit(
            "Saved source registry differs from frozen inputs; evidence was not changed"
        )
    chunks = {chunk.id: chunk for chunk in inputs.chunks}
    sources = {source.id: source for source in inputs.sources}
    if len(chunks) != len(inputs.chunks) or len(sources) != len(inputs.sources):
        raise InvalidEdit("Frozen source inventory contains duplicate IDs")

    file_hashes: dict[str, str] = {}

    def same_file(left: str, right: str) -> bool:
        if left == right:
            return True
        for name in (left, right):
            if name not in file_hashes:
                file_hashes[name] = sha256(directory.parent.parent.parent / name)
        return file_hashes[left] == file_hashes[right]

    def contains(source, chunk) -> bool:
        """Overlapping or byte-identical sources may share a canonical chunk/page."""
        if not same_file(chunk.file, source.file):
            return False
        if (source.pdf_start is None) != (source.pdf_end is None):
            return False
        if source.pdf_start is not None:
            return (
                chunk.pdf_page is not None and source.pdf_start <= chunk.pdf_page <= source.pdf_end
            )
        return True

    for chunk in inputs.chunks:
        owner = sources.get(chunk.source)
        if (
            owner is None
            or chunk.file != owner.file
            or chunk.id not in owner.chunk_ids
            or not contains(owner, chunk)
        ):
            raise InvalidEdit("Frozen source inventory has mismatched canonical chunk ownership")
    for source in inputs.sources:
        if len(source.chunk_ids) != len(set(source.chunk_ids)) or any(
            cid not in chunks or not contains(source, chunks[cid]) for cid in source.chunk_ids
        ):
            raise InvalidEdit("Frozen source inventory has mismatched chunk IDs")
    if len({item.chunk_id for item in note.evidence}) != len(note.evidence):
        raise InvalidEdit("Saved evidence contains duplicate IDs")
    for item in note.evidence:
        chunk = chunks.get(item.chunk_id)
        source = sources.get(item.source)
        if (
            chunk is None
            or source is None
            or chunk.source != item.source
            or item.chunk_id not in source.chunk_ids
            or item.text != chunk.text
            or item.title != source.title
            or item.page != page_of(chunk)
        ):
            raise InvalidEdit("Saved evidence does not match the frozen source inventory")
    found = [(section, topic) for section, topic in plan.topics() if topic.id == note.topic_id]
    if len(found) != 1 or any(sid not in sources for sid in found[0][1].sources):
        raise InvalidEdit("Saved topic plan does not match the frozen source registry")
    context_hash = hashlib.sha256(
        provenance_file.read_bytes()
        + inputs_file.read_bytes()
        + plan_file.read_bytes()
        + actual.encode()
    ).hexdigest()
    return inputs, found[0][0], found[0][1], context_hash


async def refreshed_topic(
    client: OpenRouterClient,
    models: NotesModels,
    directory: Path,
    document: NotesDocument,
    note: TopicNote,
) -> tuple[TopicNote, str | None, str | None]:
    frozen = await asyncio.to_thread(refresh_inputs, directory, document, note)
    if frozen is None:
        return note, LEGACY_REFRESH, None
    inputs, section, planned, context_hash = frozen
    selected, gaps = await select_evidence(
        client, models.selector, section, planned, inputs, Retriever(inputs.chunks)
    )
    old = {item.chunk_id for item in note.evidence}
    added = [item for item in selected if item.chunk_id not in old][:MAX_REFRESH_NEW]
    if not added:
        existing = {issue.detail for issue in evidence_gaps(note)}
        fresh = [evidence_gap(gap) for gap in gaps if gap.strip() and gap not in existing]
        if not fresh:
            return note, NO_NEW_EVIDENCE, context_hash
        candidate = note.model_copy(deep=True)
        candidate.open_issues.extend(fresh)
        return candidate, NO_NEW_EVIDENCE, context_hash
    candidate = note.model_copy(deep=True)
    candidate.evidence.extend(added)
    candidate.open_issues = [
        issue for issue in candidate.open_issues if issue not in evidence_gaps(candidate)
    ]
    candidate.open_issues.extend(evidence_gap(gap) for gap in gaps)
    return (
        candidate,
        f"Added {len(added)} excerpt(s) from this run's frozen source inputs.",
        context_hash,
    )


def create_verification(directory: Path, topic_id: str, base_revision: int) -> VerificationJob:
    store = RevisionStore(directory)
    with store.locked():
        head = store.head_revision()
        if base_revision != head:
            raise RevisionConflict(f"Revision changed; current revision is {head}")
        current = store.current()
        note = find_topic(current.document, topic_id)
        if note is None:
            raise RevisionNotFound("Topic not found")
        if not note.blocks or not note.evidence or note.status in ("no_evidence", "failed"):
            raise InvalidEdit("This topic has no text and evidence to verify")
        job = VerificationJob(
            id=new_id(),
            topic_id=topic_id,
            base_revision=head,
            status="queued",
            fingerprint=fingerprint(directory, current.document, note),
        )
        write_verification_job(directory, job)
        return job


def advance_job(
    directory: Path,
    identifier: str,
    allowed: tuple[str, ...],
    change: Callable[[VerificationJob], None],
) -> VerificationJob | None:
    with run_lock(directory):
        job = read_verification_job(directory, identifier)
        if job.status not in allowed:
            return None
        change(job)
        write_verification_job(directory, job)
        return job


def record_verification(
    directory: Path,
    identifier: str,
    check: Verification,
    refreshed: TopicNote,
    refresh_note: str | None,
    source_context: str | None,
) -> RenderJob | None:
    """Commit the result as a metadata revision if its base is still current.

    `refreshed` has the base's exact authored blocks plus validated appended evidence."""
    store = RevisionStore(directory)
    with store.locked():
        job = read_verification_job(directory, identifier)
        if job.status != "running":
            return None
        job.verification, job.verified = check, is_verified(refreshed, check)
        job.blocking = evidence_gaps(refreshed)
        job.refresh_note = refresh_note
        head = store.head_revision()
        current = store.current()
        note = find_topic(current.document, job.topic_id)
        stale = (
            head != job.base_revision
            or note is None
            or job.fingerprint != fingerprint(directory, current.document, note)
        )
        if stale:
            # Never certify newer content: keep the result, report the conflict.
            job.status, job.conflict = "done", True
            job.error = "The notes changed while the check ran; check the topic again"
            write_verification_job(directory, job)
            return None
        if source_context is not None:
            checked = refresh_inputs(directory, current.document, note)
            if checked is None or checked[3] != source_context:
                raise InvalidEdit("Frozen source context changed during verification")
        document = current.document.model_copy(deep=True)
        target = find_topic(document, job.topic_id)
        assert target is not None
        target.evidence = refreshed.evidence
        target.open_issues = refreshed.open_issues
        certify(target, check)
        view = store.commit(
            current, document, "verification", [job.topic_id], verification_job=job.id
        )
        job.status, job.revision = "done", view.info.revision
        write_verification_job(directory, job)
        return store.staged


async def run_verification(
    directory: Path, identifier: str, settings: WorkerSettings, opener: Opener
) -> None:
    try:
        started = await asyncio.to_thread(
            advance_job, directory, identifier, ("queued",), set_job("running")
        )
        if started is None:
            return
        view = await asyncio.to_thread(RevisionStore(directory).read, started.base_revision)
        note = find_topic(view.document, started.topic_id)
        if note is None:
            raise RevisionNotFound("Topic not found")
        models = NotesModels.from_settings(settings)
        async with opener() as client:
            refreshed, refresh_note, source_context = await refreshed_topic(
                client, models, directory, view.document, note
            )
            check = await verify_topic(
                client,
                models,
                directory,
                view.document,
                refreshed,
                "verify-topic-manual",
            )
        render = await asyncio.to_thread(
            record_verification,
            directory,
            identifier,
            check,
            refreshed,
            refresh_note,
            source_context,
        )
        if render is not None:
            await render_revision(directory, render.id, settings)
    except asyncio.CancelledError:
        await asyncio.shield(
            asyncio.to_thread(fail_verification, directory, identifier, INTERRUPTED)
        )
        raise
    except Exception as error:
        message = str(getattr(error, "detail", None) or error) or type(error).__name__
        print(f"Verification {identifier} failed: {error!r}")
        await asyncio.to_thread(fail_verification, directory, identifier, message)


def set_job(status: str) -> Callable[[VerificationJob], None]:
    def change(job: VerificationJob) -> None:
        job.status = status  # type: ignore[assignment]

    return change


def fail_verification(directory: Path, identifier: str, message: str) -> None:
    def change(job: VerificationJob) -> None:
        job.status, job.error = "failed", message

    try:
        advance_job(directory, identifier, FAILED_STATES, change)
    except Exception as error:
        print(f"Verification {identifier} could not be marked failed: {error!r}")


# Startup recovery, under the worker's lifetime lock.


def recover_run(directory: Path) -> None:
    suggestions = stored(directory, SUGGESTIONS, SuggestionRecord)
    jobs = stored(directory, VERIFICATIONS, VerificationJob)
    if not suggestions and not jobs:
        return
    history = RevisionStore(directory).history()
    applied = {i.suggestion: i.revision for i in history if i.suggestion}
    checked = {i.verification_job: i.revision for i in history if i.verification_job}
    with run_lock(directory):
        for record in suggestions:
            if record.id in applied and record.status != "applied":
                record.status, record.applied_revision = "applied", applied[record.id]
            elif record.status in FAILED_STATES:
                record.status, record.error = "failed", INTERRUPTED
            else:
                continue
            write_suggestion(directory, record)
        for job in jobs:
            if job.status not in FAILED_STATES:
                continue
            if job.id in checked:
                job.status, job.revision = "done", checked[job.id]
            else:
                job.status, job.error = "failed", INTERRUPTED
            write_verification_job(directory, job)


def fail_interrupted_jobs(uploads: Path) -> None:
    """A previous worker's queued/running jobs can never finish. One run's malformed
    records or history cannot stop recovery of the others."""
    for directory in uploads.glob("*/notes/*"):
        if not directory.is_dir():
            continue
        try:
            recover_run(directory)
        except Exception as error:
            print(f"AI job recovery skipped {directory}: {error!r}")
