"""Pure identity and validity rules for a teacher's decision on saved topic text."""

import hashlib
import json

from app.note_assets import image_references
from app.note_reference_tokens import source_ids_from_markdown
from app.notes import NotesDocument, TopicNote


def approval_fingerprint(document: NotesDocument, topic: TopicNote) -> str | None:
    """Bind authored text to only its frozen sources and referenced image catalog entries.

    Missing references fail closed. This deliberately reads snapshot metadata, never uploads.
    """
    if topic.status not in ("verified", "unresolved") or not any(
        block.content.strip() for block in topic.blocks
    ):
        return None
    section = next(
        (
            section
            for section in document.sections
            if any(t.topic_id == topic.topic_id for t in section.topics)
        ),
        None,
    )
    if section is None:
        return None
    source_by_id = {source.id: source for source in document.sources}
    asset_by_path = {asset.path: asset for asset in document.assets}
    source_ids = {item.source for item in topic.evidence}
    evidence_ids = {item.chunk_id for item in topic.evidence}
    image_paths: set[str] = set()
    # Each of these fields is emitted as Markdown in at least one student format.
    # Document/section headings and notation are shared by the full notes, while
    # topic/block headings are emitted in both full and standalone documents.
    markdown_fields = [
        document.title,
        section.title,
        topic.title,
        *(text for entry in document.notation for text in (entry.symbol, entry.meaning)),
        *(text for block in topic.blocks for text in (block.title or "", block.content)),
    ]
    for value in markdown_fields:
        source_ids.update(source_ids_from_markdown(value))
    try:
        for block in topic.blocks:
            if not set(block.citations) <= evidence_ids:
                return None
            image_paths.update(path for _, path, _ in image_references(block.content))
    except ValueError:
        return None
    if not source_ids <= source_by_id.keys() or not image_paths <= asset_by_path.keys():
        return None
    if any(item.chunk_id not in source_by_id[item.source].chunk_ids for item in topic.evidence):
        return None
    identity = {
        "topic": topic.model_dump(
            include={"topic_id", "title", "objectives", "blocks", "evidence"}
        ),
        "context": {
            "document_title": document.title,
            "section_title": section.title,
            "language": document.language,
            "notation": [entry.model_dump() for entry in document.notation],
            "terminology": [entry.model_dump() for entry in document.terminology],
        },
        "sources": [source_by_id[item].model_dump() for item in sorted(source_ids)],
        "assets": [asset_by_path[item].model_dump() for item in sorted(image_paths)],
    }
    encoded = json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()


def is_teacher_approved(document: NotesDocument, topic: TopicNote) -> bool:
    decision = topic.teacher_decision
    return bool(
        decision
        and decision.decision == "approved"
        and decision.fingerprint
        and decision.fingerprint == approval_fingerprint(document, topic)
    )
