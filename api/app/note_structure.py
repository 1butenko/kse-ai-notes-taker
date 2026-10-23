"""Deterministic teaching-structure gaps and the evidence gaps that outlive an edit.

Shared by generation, revisions and AI suggestions: a gap is recomputed from the saved
text, never carried over from an earlier verification.
"""

import re

from app.notes import TopicNote, VerificationIssue

EVIDENCE_GAP_FIX = "Add supporting course evidence; do not invent missing content."
STRUCTURE_FIX = "Add supporting course evidence before completing this objective."

# Explicit objective cues only: legacy/unknown objectives impose no template.
STRUCTURE_CUES = {
    "definition": r"\bdefin(?:e|ition|itions)\b|означенн|визначенн|визначити",
    "example": r"\bexamples?\b|приклад",
    "intuition": r"\bintuition\b|інтуї",
    "proof": r"\b(?:prove|proof)\b|довести|доведенн",
    "summary": r"\b(?:summary|summari[sz]e)\b|підсум",
}
# The writer may teach intuition in an overview block; both forms satisfy the objective.
EQUIVALENT_KINDS = {"intuition": {"intuition", "overview"}}


def topic_structure_issues(note: TopicNote) -> list[str]:
    """Report objective-dependent teaching gaps without inventing missing content."""
    issues = []
    objectives = " ".join(note.objectives).lower()
    evidence = {item.chunk_id for item in note.evidence}
    for kind, cue in STRUCTURE_CUES.items():
        if not re.search(cue, objectives):
            continue
        kinds = EQUIVALENT_KINDS.get(kind, {kind})
        blocks = [block for block in note.blocks if block.kind in kinds and block.content.strip()]
        if not blocks:
            issues.append(f"Objective requires a {kind} block; supporting material may be missing.")
        elif not any(evidence.intersection(block.citations) for block in blocks):
            issues.append(f"The required {kind} has no cited supporting evidence.")
    return issues


def evidence_gap(detail: str) -> VerificationIssue:
    return VerificationIssue(
        block=None, kind="citation", severity="major", detail=detail, fix=EVIDENCE_GAP_FIX
    )


def structure_gaps(note: TopicNote) -> list[VerificationIssue]:
    return [
        VerificationIssue(
            block=None,
            kind="missing_objective",
            severity="major",
            detail=detail,
            fix=STRUCTURE_FIX,
        )
        for detail in topic_structure_issues(note)
    ]


def evidence_gaps(note: TopicNote) -> list[VerificationIssue]:
    """The selector's gaps are facts about the frozen evidence: they stay visible."""
    return [
        issue for issue in note.open_issues if issue.block is None and issue.fix == EVIDENCE_GAP_FIX
    ]
