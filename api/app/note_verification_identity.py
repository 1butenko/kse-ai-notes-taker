"""Pure verifier inputs and exact candidate identity shared by API and worker."""

import hashlib
import json
from pathlib import Path

from app.notes import (
    BlockKind,
    CoursePlan,
    EvidenceItem,
    NotesDocument,
    PlannedSection,
    PlannedTopic,
    TopicNote,
)
from app.schemas import Strict


class DraftBlock(Strict):
    kind: BlockKind
    title: str | None
    content: str
    citations: list[int]


class TopicDraft(Strict):
    blocks: list[DraftBlock]


def topic_text(section: PlannedSection, topic: PlannedTopic) -> str:
    lines = [
        f"Section: {section.title}",
        f"Topic {topic.id}: {topic.title}",
        "Objectives:",
        *[f"- {o}" for o in topic.objectives],
        "Success criteria:",
        *[f"- {c}" for c in topic.success_criteria],
        f"Key terms: {', '.join(topic.key_terms)}",
    ]
    return "\n".join(lines)


def registry_text(plan: CoursePlan) -> str:
    lines = ["Notation:"]
    lines += [f"- {n.symbol}: {n.meaning}" for n in plan.notation] or ["(none)"]
    lines += ["Terminology:"]
    lines += [f"- {t.term}: {t.definition}" for t in plan.terminology] or ["(none)"]
    lines += ["Conventions:"]
    lines += [f"- {c}" for c in plan.conventions] or ["(none)"]
    return "\n".join(lines)


def context_text(plan: CoursePlan, topic: PlannedTopic) -> str:
    order = [t for _, t in plan.topics()]
    position = next(i for i, t in enumerate(order) if t.id == topic.id)
    before = ", ".join(f"{t.id} {t.title}" for t in order[:position]) or "(none)"
    after = ", ".join(f"{t.id} {t.title}" for t in order[position + 1 :]) or "(none)"
    prerequisites = ", ".join(topic.prerequisites) or "(none)"
    return (
        f"Prerequisites: {prerequisites}\nTopics before this one: {before}\n"
        f"Topics after this one (do not cover them): {after}"
    )


def evidence_text(evidence: list[EvidenceItem]) -> str:
    return "\n\n".join(
        f"E{i} [{e.role}] ({e.title}, {e.page or 'no page'}):\n{e.text}"
        for i, e in enumerate(evidence)
    )


def draft_text(draft: TopicDraft) -> str:
    return "\n\n".join(
        f"B{i} [{b.kind}] {b.title or ''} (cites {', '.join(f'E{c}' for c in b.citations)}):\n"
        f"{b.content}"
        for i, b in enumerate(draft.blocks)
    )


def verification_inputs(
    directory: Path, document: NotesDocument, note: TopicNote
) -> tuple[CoursePlan, PlannedSection, PlannedTopic]:
    try:
        stored_plan = CoursePlan.model_validate_json((directory / "plan.json").read_text())
    except (OSError, ValueError):
        stored_plan = None
    originals = {t.id: t for _, t in stored_plan.topics()} if stored_plan else {}

    def planned(item: TopicNote) -> PlannedTopic:
        found = originals.get(item.topic_id)
        base = found or PlannedTopic(
            id=item.topic_id,
            title=item.title,
            sessions=[],
            objectives=[],
            success_criteria=[],
            prerequisites=[],
            sources=[],
            key_terms=[],
        )
        return base.model_copy(update={"title": item.title, "objectives": list(item.objectives)})

    sections = [
        PlannedSection(title=section.title, topics=[planned(t) for t in section.topics])
        for section in document.sections
    ]
    plan = CoursePlan(
        title=document.title,
        sections=sections,
        notation=document.notation,
        terminology=document.terminology,
        conventions=stored_plan.conventions if stored_plan else [],
    )
    section, topic = next((s, t) for s, t in plan.topics() if t.id == note.topic_id)
    return plan, section, topic


def draft_of(note: TopicNote) -> TopicDraft:
    index = {item.chunk_id: i for i, item in enumerate(note.evidence)}
    return TopicDraft(
        blocks=[
            DraftBlock(
                kind=block.kind,
                title=block.title,
                content=block.content,
                citations=[index[c] for c in block.citations if c in index],
            )
            for block in note.blocks
        ]
    )


def fingerprint(directory: Path, document: NotesDocument, note: TopicNote) -> str:
    """Identity of the ordered candidate, evidence, registry and shown verifier context."""
    plan, section, topic = verification_inputs(directory, document, note)
    material = {
        "topic": note.topic_id,
        "blocks": [block.model_dump() for block in note.blocks],
        "evidence": [item.model_dump() for item in note.evidence],
        "shown": [
            topic_text(section, topic),
            context_text(plan, topic),
            registry_text(plan),
            evidence_text(note.evidence),
            draft_text(draft_of(note)),
        ],
    }
    text = json.dumps(material, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(text.encode()).hexdigest()
