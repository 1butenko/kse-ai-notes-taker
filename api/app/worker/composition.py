"""Global composition: collect topic notes in plan order and harmonize them with targeted edits."""

from langfuse import get_client

from app.notes import CoursePlan, NotesSection, TopicNote
from app.schemas import Strict
from app.worker.llm import ask, chat
from app.worker.models import ModelSpec
from app.worker.openrouter import OpenRouterClient
from app.worker.topics import registry_text

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
every formula that is correct, and the language. Do not rewrite blocks that are fine; return
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


async def harmonize(
    client: OpenRouterClient,
    spec: ModelSpec,
    plan: CoursePlan,
    sections: list[NotesSection],
) -> int:
    """Apply consistency edits in place, a batch of topics at a time; returns the edit count."""
    notes = [n for s in sections for n in s.topics if n.blocks]
    blocks = {b.id: b for n in notes for b in n.blocks}
    outline = outline_text(sections)
    applied = 0
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
                spec=spec,
            )
            allowed = {b.id for n in batch for b in n.blocks}
            for edit in result.edits:
                if edit.block in allowed and edit.content.strip():
                    blocks[edit.block].content = edit.content
                    applied += 1
        span.update(output={"edits": applied})
    return applied
