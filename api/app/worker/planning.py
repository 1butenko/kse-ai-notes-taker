"""Planning: draft a topic hierarchy from the syllabus and materials, review coverage, revise."""

import json

from langfuse import get_client

from app.notes import (
    CourseNotation,
    CoursePlan,
    CoverageIssue,
    CoverageReview,
    Inputs,
    bind_notation,
    validate_topic_ids,
)
from app.syllabus import Transcript
from app.worker.artifacts import RunStore
from app.worker.llm import ask, chat
from app.worker.models import NotesModels
from app.worker.openrouter import OpenRouterClient

PREVIEW_CHARS = 500

PLANNER_PROMPT = """\
You plan the lecture notes of a university course.

You get the syllabus sessions (S0, S1, ...) with their topics and readings, and the course
materials mapped to them (R0, R1, ...) with their outline and the opening of their text.
Build the notes' topic hierarchy:
- sections: the main parts of the course, in teaching order; each holds topics.
- topics: units that one note of a few pages can cover well. id is "T1", "T2", ... in order.
  sessions: the S numbers it belongs to. sources: the R numbers whose text supports it.
  objectives: what a student must be able to state, derive or do after reading it.
  success_criteria: checkable statements a reviewer can use to decide the note is complete,
  e.g. "states the rank-nullity theorem with its assumptions and one worked example".
  prerequisites: ids of earlier topics it relies on (never later ones).
  key_terms: the terms, theorems and symbols it introduces; used to search the materials.
- Cover every syllabus session topic and subtopic. Do not split one idea across topics or
  repeat it in two. Order topics so every concept is introduced before it is used.
- Review, revision, recap or exam-preparation sessions get no topic of their own: add their
  S number to the sessions of the topics they review.
- notation: one entry per symbol the notes should use consistently, with its meaning.
  Prefer the notation of the main course book. terminology: key terms with a one-line
  definition. conventions: other shared rules (e.g. "vectors are columns").
- title: the course title. Write in the syllabus language.
When you get a previous plan and reviewer issues, return the full revised plan, fixing every
blocking issue and keeping what was fine.
"""

LECTURE_RULE = """
This plan is for one lecture of the course (session S0), not the whole course. Return
exactly one section, named after the lecture, holding 1 to 4 topics that together cover
that lecture; each topic becomes one section of the lecture's note. title: the lecture's
title. Earlier lectures are not part of this plan: never list them as prerequisites.
"""

LECTURE_TOPICS = 4

COVERAGE_PROMPT = """\
You review the topic plan of a course's lecture notes against an explicit rubric.

Check:
1. Syllabus coverage: every session topic and subtopic is covered by some topic.
2. No duplicates: no idea is planned in two topics.
3. Granularity: each topic fits one note of a few pages; none is trivial or a whole chapter.
4. Evidence: every topic lists sources whose outline or text plausibly supports it. When no
   listed material covers a topic at all, report weak_evidence once: it is a gap in the
   materials that the plan cannot fix.
5. Ordering: prerequisites come earlier; concepts are introduced before use.
6. Objectives: objectives and success criteria are specific and checkable.

Return each concrete problem as an issue naming the affected topic ids, what is wrong and
the fix. severity "blocking" when the notes would be wrong, incomplete or confusing without
the fix; "minor" otherwise. approved is true only when there are no blocking issues. Do not
approve by default, and do not invent problems.
"""


def syllabus_text(transcript: Transcript) -> str:
    lines = []
    for i, session in enumerate(transcript.sessions):
        lines.append(f"S{i}: {session.label}: {session.topic}")
        lines += [f"  - {s}" for s in session.subtopics]
        for reading in session.required_readings + session.optional_readings:
            lines.append(f"  reading: {reading.raw}")
    return "\n".join(lines) or "(no sessions)"


def inventory_text(inputs: Inputs) -> str:
    chunks = {c.id: c for c in inputs.chunks}
    lines = []
    for source in inputs.sources:
        pages = f"PDF pp. {source.pdf_start}-{source.pdf_end}" if source.pdf_start else "whole file"
        sessions = ", ".join(f"S{s}" for s in source.sessions)
        lines.append(f"R{source.id}: {source.title} [{source.label or pages}] for {sessions}")
        if source.outline:
            lines.append("  outline: " + "; ".join(source.outline[:40]))
        opening = " ".join(chunks[c].text for c in source.chunk_ids[:2])
        lines.append(f"  opening: {' '.join(opening.split())[:PREVIEW_CHARS]}")
    return "\n".join(lines) or "(no materials)"


def planner_input(
    transcript: Transcript,
    inputs: Inputs,
    previous: CoursePlan | None,
    issues: list,
    sheet: CourseNotation | None = None,
) -> str:
    parts = [
        f"Syllabus language: {transcript.language or 'unknown'}",
        "",
        "Syllabus sessions:",
        syllabus_text(transcript),
        "",
        "Course materials:",
        inventory_text(inputs),
    ]
    if sheet and (sheet.notation or sheet.terminology):
        parts += [
            "",
            "Course notation (binding: earlier lectures use these symbols and terms with these "
            "meanings. Reuse them, never give them another meaning, and add entries only for "
            "what this lecture introduces):",
            sheet.model_dump_json(indent=1),
        ]
    if previous:
        parts += [
            "",
            "Previous plan:",
            previous.model_dump_json(indent=1),
            "",
            "Reviewer issues to fix:",
            json.dumps([i.model_dump() for i in issues], ensure_ascii=False, indent=1),
        ]
    return "\n".join(parts)


def is_lecture(transcript: Transcript) -> bool:
    """A lecture run's transcript is scoped to its one session."""
    return len(transcript.sessions) == 1


def check_references(plan: CoursePlan, transcript: Transcript, inputs: Inputs) -> list:
    """Deterministic checks the reviewer would otherwise have to spot."""
    issues = []
    if is_lecture(transcript) and (
        len(plan.sections) != 1 or not 1 <= len(plan.topics()) <= LECTURE_TOPICS
    ):
        issues.append(
            f"A lecture plan has one section with 1 to {LECTURE_TOPICS} topics, not "
            f"{len(plan.sections)} sections with {len(plan.topics())} topics"
        )
    ids = [t.id for _, t in plan.topics()]
    try:
        validate_topic_ids(ids)
    except ValueError as error:
        issues.append(str(error))
    seen: set[str] = set()
    for _, topic in plan.topics():
        if topic.id in seen:
            issues.append(f"{topic.id}: duplicate topic id")
        bad_sessions = [s for s in topic.sessions if not 0 <= s < len(transcript.sessions)]
        bad_sources = [s for s in topic.sources if not 0 <= s < len(inputs.sources)]
        later = [p for p in topic.prerequisites if p not in seen]
        if bad_sessions:
            issues.append(f"{topic.id}: unknown sessions {bad_sessions}")
        if bad_sources:
            issues.append(f"{topic.id}: unknown sources {bad_sources}")
        if later:
            issues.append(f"{topic.id}: prerequisites {later} are not earlier topics")
        seen.add(topic.id)
    uncovered = set(range(len(transcript.sessions))) - {
        s for _, t in plan.topics() for s in t.sessions
    }
    if uncovered:
        issues.append(f"No topic covers sessions {sorted(uncovered)}")
    if not ids:
        issues.append("The plan has no topics")
    return issues


async def plan_course(
    client: OpenRouterClient,
    models: NotesModels,
    store: RunStore,
    transcript: Transcript,
    inputs: Inputs,
    rounds: int,
    sheet: CourseNotation | None = None,
) -> CoursePlan:
    """Plan, review and revise until approved or out of rounds; the last plan is used.

    A lecture run passes the course notation sheet: it is binding, so where the plan
    disagrees with it the sheet's meaning is kept.
    """
    with get_client().start_as_current_observation(
        name="plan-course",
        input={"sessions": len(transcript.sessions), "sources": len(inputs.sources)},
    ) as span:
        plan: CoursePlan | None = None
        issues: list[CoverageIssue] = []
        lecture = LECTURE_RULE if is_lecture(transcript) else ""
        for round in range(1, rounds + 1):
            plan = await ask(
                client,
                chat(
                    PLANNER_PROMPT + lecture,
                    planner_input(transcript, inputs, plan, issues, sheet),
                ),
                CoursePlan,
                "course_plan",
                step="draft-course-plan",
                spec=models.planner,
            )
            store.write(f"plan/draft-{round}.json", plan)

            review = await ask(
                client,
                chat(
                    COVERAGE_PROMPT + lecture,
                    "\n".join(
                        [
                            "Syllabus sessions:",
                            syllabus_text(transcript),
                            "",
                            "Course materials:",
                            inventory_text(inputs),
                            "",
                            "Plan:",
                            plan.model_dump_json(indent=1),
                        ]
                    ),
                ),
                CoverageReview,
                "coverage_review",
                step="check-coverage",
                spec=models.coverage,
            )
            for problem in check_references(plan, transcript, inputs):
                review.issues.append(
                    CoverageIssue(
                        kind="ordering" if "prerequisites" in problem else "missing_topic",
                        severity="blocking",
                        topics=[],
                        detail=problem,
                        fix="Fix the reference.",
                    )
                )
            store.write(f"plan/review-{round}.json", review)
            blocking = review.blocking()
            issues = blocking + review.evidence_gaps()
            store.log("planning", f"Round {round}: {len(blocking)} blocking issues")
            if not blocking:
                break
        else:
            store.warn(
                f"Course plan still has {len(blocking)} blocking issues after {rounds} rounds"
            )
        for gap in review.evidence_gaps():
            store.warn(f"Thin evidence for {', '.join(gap.topics) or 'a topic'}: {gap.detail}")

        assert plan is not None
        if sheet is not None:
            plan = bind_notation(plan, sheet)
        validate_topic_ids([topic.id for _, topic in plan.topics()])
        store.write("plan.json", plan)
        span.update(
            output={"topics": [t.title for _, t in plan.topics()], "open_issues": len(blocking)}
        )
        return plan
