"""Global composition: collect topic notes in plan order and harmonize them with targeted edits."""

import re
from collections import Counter

from langfuse import get_client

from app.notes import CoursePlan, NotesSection, TopicNote, VerificationIssue
from app.schemas import Strict
from app.worker.llm import ask, chat
from app.worker.models import NotesModels
from app.worker.openrouter import OpenRouterClient
from app.worker.references import BLANK_LINE, LABEL, math_regions, prose
from app.worker.topics import (
    DraftBlock,
    TopicDraft,
    add_structure_issues,
    is_clean,
    registry_text,
    verification_issues,
    verify,
)

BATCH_TOPICS = 6


class BlockEdit(Strict):
    block: str
    content: str
    reason: str


class ConsistencyEdits(Strict):
    edits: list[BlockEdit]


CONSISTENCY_PROMPT = """\
You harmonize lecture notes that were written topic by topic.

You get the shared notation and terminology, the outline of the whole document, and some of
its topics with their blocks (id in brackets). Return targeted edits only for blocks that need
them:
- unify notation and terminology with the registry and with the other topics;
- remove repetition of something an earlier topic already explains, replacing it with a
  short reference ("see Topic T3");
- add cross-references where a block uses a concept from another topic;
- fix the order in which concepts are introduced when a block uses one before it is defined.
Each edit gives the block id and its complete new content. Keep the mathematical meaning,
every formula, every declared equation/figure/table label, every citation and source ID,
the block IDs, and the language. Keep the intuition → definition/properties → example →
summary teaching order when evidence supports it; do not fill evidence gaps with inventions.
Do not rewrite blocks that are fine; return
no edits when nothing needs changing.
"""


def collect(plan: CoursePlan, notes: dict[str, TopicNote]) -> list[NotesSection]:
    return [
        NotesSection(
            title=section.title,
            topics=[notes[t.id] for t in section.topics if t.id in notes],
        )
        for section in plan.sections
    ]


def outline_text(sections: list[NotesSection]) -> str:
    lines = []
    for section in sections:
        lines.append(section.title)
        for note in section.topics:
            titled = [b.title for b in note.blocks if b.title and b.kind != "summary"]
            lines.append(f"  {note.topic_id} {note.title}: {'; '.join(titled)}")
    return "\n".join(lines)


def topic_blocks(note: TopicNote) -> str:
    return "\n\n".join(
        [f"Topic {note.topic_id}: {note.title}"]
        + [f"[{b.id}] ({b.kind}) {b.title or ''}\n{b.content}" for b in note.blocks]
    )


def source_citations(content: str) -> list[str]:
    """Keep the complete attached citation suffix, including nested/escaped brackets."""
    visible = prose(content).replace("\r", "")
    offsets = [index for index, char in enumerate(content) if char != "\r"]
    citations = []
    for match in re.finditer(r"(?<![\w/])@src-[A-Za-z0-9_.:-]+", visible):
        end = match.end()
        space = re.match(r"[ \t]*(?:\n[ \t]*)?", visible[end:])
        cursor = end + space.end()
        if visible[cursor : cursor + 1] == "[":
            depth = 0
            while cursor < len(visible):
                if BLANK_LINE.match(visible, cursor):
                    break
                char = visible[cursor]
                if char == "\\":
                    cursor += 2
                    continue
                depth += {"[": 1, "]": -1}.get(char, 0)
                cursor += 1
                if depth == 0:
                    end = cursor
                    break
        citations.append(content[offsets[match.start()] : offsets[end - 1] + 1])
    return citations


def preserves_content(before: str, after: str) -> bool:
    """Harmonization may change prose, but not formulas, labels or citations."""

    def protected(content: str) -> tuple:
        visible = prose(content)
        return (
            Counter(content[start:end] for start, end in math_regions(content)),
            Counter(LABEL.findall(visible)),
            Counter(re.findall(r"\[[^\]\n]*@src-[^\]\n]+\]", visible)),
            Counter(source_citations(content)),
        )

    return protected(before) == protected(after)


async def recheck_topic(
    client: OpenRouterClient, models: NotesModels, plan: CoursePlan, note: TopicNote
) -> None:
    """Verify the full displayed topic with its original evidence and saved objectives."""
    note.status = "unresolved"
    note.verification_stale = True
    # Evidence/structure gaps survive an LLM pass: missing readings cannot be harmonized away.
    retained = [i for i in note.open_issues if i.kind in ("citation", "missing_objective")]
    try:
        section, topic = next((s, t) for s, t in plan.topics() if t.id == note.topic_id)
        topic = topic.model_copy(update={"objectives": list(note.objectives)})
        evidence_ids = {item.chunk_id: i for i, item in enumerate(note.evidence)}
        draft = TopicDraft(
            blocks=[
                DraftBlock(
                    kind=b.kind,
                    title=b.title,
                    content=b.content,
                    citations=[evidence_ids[c] for c in b.citations if c in evidence_ids],
                )
                for b in note.blocks
            ]
        )
        spec = models.verifier
        check = await verify(
            client, spec, plan, section, topic, note.evidence, draft, "verify-harmonized-topic"
        )
        if check.escalate:
            spec = models.escalation
            check = await verify(
                client,
                spec,
                plan,
                section,
                topic,
                note.evidence,
                draft,
                "verify-harmonized-topic-escalated",
            )
        note.verifier = spec.model
        note.rounds += 1
        note.verification_stale = False
        note.open_issues = retained + [
            i for i in verification_issues(check) if i.severity == "major" and i not in retained
        ]
        note.status = "verified" if is_clean(check) and not note.open_issues else "unresolved"
    except Exception:
        # The saved content remains available even if the verification service fails.
        note.open_issues.append(
            VerificationIssue(
                block=None,
                kind="clarity",
                severity="major",
                detail="Changed topic could not be freshly verified after harmonization.",
                fix="Recheck this exact topic against its evidence before relying on it.",
            )
        )
    add_structure_issues(note)


async def harmonize(
    client: OpenRouterClient,
    models: NotesModels,
    plan: CoursePlan,
    sections: list[NotesSection],
) -> int:
    """Apply consistency edits in place, a batch of topics at a time; returns the edit count."""
    notes = [n for s in sections for n in s.topics if n.blocks]
    blocks = {b.id: b for n in notes for b in n.blocks}
    outline = outline_text(sections)
    applied = 0
    changed: set[str] = set()
    with get_client().start_as_current_observation(
        name="compose-notes", input={"topics": len(notes)}
    ) as span:
        for start in range(0, len(notes), BATCH_TOPICS):
            batch = notes[start : start + BATCH_TOPICS]
            result = await ask(
                client,
                chat(
                    CONSISTENCY_PROMPT,
                    registry_text(plan),
                    "Document outline:\n" + outline,
                    "\n\n".join(topic_blocks(n) for n in batch),
                ),
                ConsistencyEdits,
                "consistency_edits",
                step="harmonize-notes",
                spec=models.consistency,
            )
            allowed = {b.id for n in batch for b in n.blocks}
            for edit in result.edits:
                if (
                    edit.block in allowed
                    and edit.content.strip()
                    and edit.content != blocks[edit.block].content
                    and preserves_content(blocks[edit.block].content, edit.content)
                ):
                    blocks[edit.block].content = edit.content
                    changed.add(edit.block)
                    applied += 1
        for note in notes:
            if any(b.id in changed for b in note.blocks):
                await recheck_topic(client, models, plan, note)
        span.update(output={"edits": applied})
    return applied
