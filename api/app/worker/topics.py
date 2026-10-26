"""Topic generation: select evidence, synthesize a note, verify it and revise with feedback."""

import json
from typing import Literal

from langfuse import get_client

from app.note_quality import normalized, substantive
from app.note_structure import evidence_gap, structure_gaps
from app.note_verification_identity import (
    TopicDraft,
    context_text,
    draft_text,
    evidence_text,
    registry_text,
    topic_text,
)
from app.notes import (
    Chunk,
    CoursePlan,
    EvidenceItem,
    Inputs,
    NoteBlock,
    PlannedSection,
    PlannedTopic,
    Role,
    TopicNote,
    Verification,
    VerificationIssue,
    topic_filename,
)
from app.schemas import Strict
from app.worker.artifacts import RunStore
from app.worker.llm import ask, chat
from app.worker.models import ModelSpec, NotesModels
from app.worker.openrouter import OpenRouterClient
from app.worker.sources import Retriever

TOPIC_CANDIDATES = 24
OTHER_CANDIDATES = 8
MAX_SELECTED_EVIDENCE = 16


# Evidence selection.


class EvidenceChoice(Strict):
    candidate: int
    role: Role
    relevance: int
    reason: str


class EvidenceSelection(Strict):
    selected: list[EvidenceChoice]
    gaps: list[str]


SELECTOR_PROMPT = """\
You select the evidence for one topic of a course's lecture notes.

You get the topic with its objectives and candidate excerpts (C0, C1, ...) retrieved from the
course materials. Keep only candidates that help a writer meet the objectives, at most 16:
- role: what the excerpt contributes: definition, theorem (or lemma, proposition), proof,
  example, intuition, exercise, background (needed context) or complementary (a second
  reading's angle on the same idea).
- relevance: 1-5, 5 being essential.
- reason: one short sentence.
Prefer excerpts from the topic's own sources; keep a complementary one from another reading
when it adds a different explanation or example. gaps: objectives no candidate supports.
"""


def page_of(chunk: Chunk) -> str | None:
    if chunk.printed_page:
        return f"p. {chunk.printed_page}"
    return f"PDF p. {chunk.pdf_page}" if chunk.pdf_page else None


def candidates_for(topic: PlannedTopic, inputs: Inputs, retriever: Retriever) -> list[Chunk]:
    query = " ".join([topic.title, *topic.key_terms, *topic.objectives])
    own = {
        chunk_id
        for source in inputs.sources
        if source.id in topic.sources
        for chunk_id in source.chunk_ids
    }
    found: list[Chunk] = []
    seen: set[str] = set()

    def add(candidates: list[Chunk], limit: int) -> None:
        for chunk in candidates:
            if len(found) >= limit:
                return
            if chunk.id not in seen:
                found.append(chunk)
                seen.add(chunk.id)

    # Reserve distinct objectives before the broad title query. Each subquery is bounded;
    # even a long plan cannot cause more than the fixed candidate budget of searches.
    objective_queries = list(dict.fromkeys([*topic.objectives, *topic.key_terms]))[:12]
    if own:
        for objective in objective_queries:
            add(retriever.search(objective, 2, own), TOPIC_CANDIDATES)
        add(retriever.search(query, TOPIC_CANDIDATES, own), TOPIC_CANDIDATES)
    others: list[Chunk] = []
    other_seen = set(seen)
    for objective in objective_queries[:4]:
        for chunk in retriever.search(objective, 2):
            if chunk.id not in other_seen and len(others) < OTHER_CANDIDATES:
                others.append(chunk)
                other_seen.add(chunk.id)
    for chunk in retriever.search(query, TOPIC_CANDIDATES + OTHER_CANDIDATES):
        if chunk.id not in other_seen and len(others) < OTHER_CANDIDATES:
            others.append(chunk)
            other_seen.add(chunk.id)
    return [*found, *others]


async def select_evidence(
    client: OpenRouterClient,
    spec: ModelSpec,
    section: PlannedSection,
    topic: PlannedTopic,
    inputs: Inputs,
    retriever: Retriever,
) -> tuple[list[EvidenceItem], list[str]]:
    candidates = candidates_for(topic, inputs, retriever)
    if not candidates:
        return [], ["No excerpt of the course materials matches this topic"]
    titles = {s.id: s.title for s in inputs.sources}
    listing = [
        f"C{i} ({titles[c.source]}, {page_of(c) or 'no page'}):\n{c.text}"
        for i, c in enumerate(candidates)
    ]
    result = await ask(
        client,
        chat(SELECTOR_PROMPT, topic_text(section, topic), "Candidates:\n\n" + "\n\n".join(listing)),
        EvidenceSelection,
        "evidence_selection",
        step="select-evidence",
        spec=spec,
    )
    chosen: dict[int, EvidenceChoice] = {}
    for choice in result.selected:
        if 0 <= choice.candidate < len(candidates) and choice.candidate not in chosen:
            chosen[choice.candidate] = choice
    evidence = [
        EvidenceItem(
            chunk_id=candidates[i].id,
            source=candidates[i].source,
            title=titles[candidates[i].source],
            page=page_of(candidates[i]),
            role=choice.role,
            relevance=max(1, min(5, choice.relevance)),
            reason=choice.reason,
            text=candidates[i].text,
        )
        for i, choice in sorted(chosen.items(), key=lambda c: (-c[1].relevance, c[0]))[
            :MAX_SELECTED_EVIDENCE
        ]
    ]
    return evidence, result.gaps


# Synthesis.


WRITER_PROMPT = """\
You write one topic of a university course's lecture notes from the selected evidence.

Combine the readings into one clear explanation; do not summarise them one by one.
- Teach intuition first (overview or intuition), then definitions/properties, a worked example,
  and a short summary when the evidence supports them and the objectives need them.
  Include theorems (with every assumption) or proofs only when relevant to the objectives
  and supported by evidence. No topic must contain a theorem. Never invent a definition,
  example, fact, source, author, year or page to fill a template; leave unsupported gaps clear.
- content is Pandoc Markdown. Mathematics in standard LaTeX: $...$ inline, $$...$$ for
  display; \\mathrm{...} rather than {\\rm ...}, no custom macros. Put a blank line before
  lists. Do not use headings (#) inside content; the block title is the heading.
- Use the shared notation and terminology exactly; introduce any new symbol before using it.
- citations: the evidence numbers (E0, E1, ... as integers) supporting the block. Every
  claim, formula and example must be supported by the cited evidence. Add standard
  explanatory steps freely, but never facts the evidence does not support.
- Meet every objective and success criterion. Write in the language of the syllabus.
When you get a previous draft and reviewer issues, return the full revised draft: fix every
issue, keep what was correct and keep its citations.
"""


async def synthesize(
    client: OpenRouterClient,
    spec: ModelSpec,
    plan: CoursePlan,
    section: PlannedSection,
    topic: PlannedTopic,
    evidence: list[EvidenceItem],
    language: str | None,
    previous: TopicDraft | None = None,
    issues: list[VerificationIssue] | None = None,
) -> TopicDraft:
    parts = [
        f"Language: {language or 'the language of the topic title'}",
        topic_text(section, topic),
        context_text(plan, topic),
        registry_text(plan),
        "Evidence:\n\n" + evidence_text(evidence),
    ]
    if previous is not None:
        parts += [
            "Previous draft:\n\n" + draft_text(previous),
            "Reviewer issues:\n"
            + json.dumps([i.model_dump() for i in issues or []], ensure_ascii=False, indent=1),
        ]
    return await ask(
        client,
        chat(WRITER_PROMPT, *parts),
        TopicDraft,
        "topic_draft",
        step="revise-topic" if previous is not None else "synthesize-topic",
        spec=spec,
    )


# Verification.


class TopicCheck(Strict):
    passed: bool
    issues: list[VerificationIssue]
    escalate: bool
    escalation_reason: str | None


def is_clean(check: TopicCheck | Verification) -> bool:
    """The shared certification rule, including a final verifier's uncertainty."""
    return check.passed and not check.escalate and not any(substantive(i) for i in check.issues)


def verification_issues(check: TopicCheck | Verification) -> list[VerificationIssue]:
    issues = normalized(check.issues)
    if check.escalate:
        issues.append(
            VerificationIssue(
                block=None,
                kind="clarity",
                severity="major",
                detail="The verifier could not confidently check this topic: "
                + (check.escalation_reason or "no reason given"),
                fix="Review the flagged material manually or add supporting course evidence.",
            )
        )
    return issues


VERIFIER_PROMPT = """\
You verify one topic of a course's lecture notes against the evidence it was written from.

Check every block (B0, B1, ...):
- Each claim, formula and example is supported by the evidence it cites; citations point at
  evidence that states the actual claim (unsupported_claim, citation). Related subject
  matter or a valid evidence ID alone does not support a claim. Evidence may be missing.
- Equations, derivations and worked examples are mathematically correct (math_error).
- Theorems state all their assumptions (assumption).
- Notation and terms follow the shared registry (notation).
- Every objective and success criterion is met (missing_objective; block null). Evaluate
  intuition, definitions/properties, worked examples and summary against the objectives and
  available evidence; do not require a theorem in every topic. Missing evidence is a visible
  gap, never a reason to invent material to complete a template.
- The explanation is clear enough for a student (clarity).
For each problem give the block number, what is wrong and the exact fix. A citation or
unsupported_claim issue is major because source support is missing; ordinary clarity and
style issues can be minor. passed is true only when there are no major issues. Set escalate
to true, with a reason,
when a proof or derivation is too hard to check confidently, when sources conflict, or when
you are unsure an error is real. Material missing from the course readings is a known gap,
not a reason to escalate: report what it leaves unsupported as citation issues.
"""


async def verify(
    client: OpenRouterClient,
    spec: ModelSpec,
    plan: CoursePlan,
    section: PlannedSection,
    topic: PlannedTopic,
    evidence: list[EvidenceItem],
    draft: TopicDraft,
    step: str,
) -> TopicCheck:
    check = await ask(
        client,
        chat(
            VERIFIER_PROMPT,
            topic_text(section, topic),
            context_text(plan, topic),
            registry_text(plan),
            "Evidence:\n\n" + evidence_text(evidence),
            "Draft:\n\n" + draft_text(draft),
        ),
        TopicCheck,
        "topic_verification",
        step=step,
        spec=spec,
    )
    check.issues = normalized(check.issues)
    majors = [i for i in check.issues if i.severity == "major"]
    check.passed = not majors and not check.escalate
    return check


def add_structure_issues(note: TopicNote) -> None:
    """Use the existing open issues/status for deterministic learning gaps."""
    existing = {issue.detail for issue in note.open_issues}
    note.open_issues += [issue for issue in structure_gaps(note) if issue.detail not in existing]
    if note.open_issues and note.status == "verified":
        note.status = "unresolved"


def to_note(
    topic: PlannedTopic,
    draft: TopicDraft,
    evidence: list[EvidenceItem],
    status: Literal["verified", "unresolved"],
    rounds: int,
    verifier: str,
    open_issues: list[VerificationIssue],
) -> TopicNote:
    def chunk_ids(citations: list[int]) -> list[str]:
        cited = [evidence[c].chunk_id for c in citations if 0 <= c < len(evidence)]
        return list(dict.fromkeys(cited))

    blocks = [
        NoteBlock(
            id=f"{topic.id}.{n}",
            kind=block.kind,
            title=block.title,
            content=block.content,
            citations=chunk_ids(block.citations),
        )
        for n, block in enumerate(draft.blocks, 1)
    ]
    return TopicNote(
        topic_id=topic.id,
        objectives=list(topic.objectives),
        title=topic.title,
        status=status,
        blocks=blocks,
        evidence=evidence,
        rounds=rounds,
        verifier=verifier,
        open_issues=open_issues,
    )


async def generate_topic(
    client: OpenRouterClient,
    models: NotesModels,
    store: RunStore,
    plan: CoursePlan,
    section: PlannedSection,
    topic: PlannedTopic,
    inputs: Inputs,
    retriever: Retriever,
    language: str | None,
    revisions: int,
) -> TopicNote:
    folder = f"topics/{topic_filename(topic.id)}"
    with get_client().start_as_current_observation(
        name="generate-topic", input={"topic": topic.title, "objectives": topic.objectives}
    ) as span:
        evidence, gaps = await select_evidence(
            client, models.selector, section, topic, inputs, retriever
        )
        store.write(
            f"{folder}/evidence.json",
            json.dumps(
                {"items": [e.model_dump() for e in evidence], "gaps": gaps},
                ensure_ascii=False,
                indent=2,
            ),
        )
        if not evidence:
            span.update(level="WARNING", status_message="No evidence")
            return TopicNote(
                topic_id=topic.id,
                objectives=list(topic.objectives),
                title=topic.title,
                status="no_evidence",
                blocks=[],
                evidence=[],
                rounds=0,
                verifier=None,
                open_issues=[evidence_gap(gap) for gap in gaps],
            )

        store.log("topics", f"{topic.id}: writing from {len(evidence)} excerpts")
        draft = await synthesize(client, models.writer, plan, section, topic, evidence, language)
        escalated = False
        check: TopicCheck | None = None
        spec = models.verifier
        for round in range(1, revisions + 2):
            store.write(f"{folder}/draft-{round}.json", draft)
            spec = models.escalation if escalated else models.verifier
            step = "verify-topic-escalated" if escalated else "verify-topic"
            store.log("topics", f"{topic.id}: checking, round {round} ({spec.model})")
            check = await verify(client, spec, plan, section, topic, evidence, draft, step)
            if check.escalate and not escalated:
                escalated = True
                spec = models.escalation
                store.log("topics", f"{topic.id}: escalated check, round {round} ({spec.model})")
                check = await verify(
                    client, spec, plan, section, topic, evidence, draft, "verify-topic-escalated"
                )
            store.write(
                f"{folder}/verification-{round}.json",
                Verification(
                    round=round,
                    model=spec.model,
                    passed=is_clean(check),
                    issues=check.issues,
                    escalate=check.escalate,
                    escalation_reason=check.escalation_reason,
                ),
            )
            if is_clean(check) or round > revisions:
                break
            if round >= 2:
                escalated = True
            majors = sum(i.severity == "major" for i in check.issues)
            store.log("topics", f"{topic.id}: revising {majors} major issues")
            draft = await synthesize(
                client,
                models.writer,
                plan,
                section,
                topic,
                evidence,
                language,
                draft,
                check.issues,
            )

        assert check is not None
        open_issues = [i for i in verification_issues(check) if i.severity == "major"]
        open_issues += [evidence_gap(gap) for gap in gaps]
        note = to_note(
            topic,
            draft,
            evidence,
            "verified" if is_clean(check) else "unresolved",
            round,
            spec.model,
            open_issues,
        )
        add_structure_issues(note)
        span.update(
            output={"status": note.status, "blocks": len(note.blocks), "rounds": round},
            level="DEFAULT" if is_clean(check) else "WARNING",
        )
        return note
