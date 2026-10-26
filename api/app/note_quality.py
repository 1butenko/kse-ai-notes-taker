"""Shared policy for substantive source-support findings in note checks."""

from app.notes import NoteBlock, Verification, VerificationIssue

SOURCE_SUPPORT_KINDS = frozenset({"citation", "unsupported_claim"})


def substantive(issue: VerificationIssue) -> bool:
    return issue.severity == "major" or issue.kind in SOURCE_SUPPORT_KINDS


def normalized(issues: list[VerificationIssue]) -> list[VerificationIssue]:
    """A source-support failure blocks certification even if the model called it minor."""
    return [
        issue.model_copy(update={"severity": "major"})
        if issue.kind in SOURCE_SUPPORT_KINDS and issue.severity != "major"
        else issue
        for issue in issues
    ]


def changed_block_ids(base: list[NoteBlock], proposed: list[NoteBlock]) -> set[str]:
    """Only content changes and insertions count; identical replacement copies do not."""
    original = {block.id: block for block in base}
    return {
        block.id for block in proposed if block.id not in original or block != original[block.id]
    }


def changed_source_issues(
    check: Verification | None, blocks: list[NoteBlock], changed_ids: set[str]
) -> list[VerificationIssue]:
    """Source-support findings about edited/inserted blocks, including old saved checks."""
    if check is None:
        return []
    return [
        issue
        for issue in normalized(check.issues)
        if issue.kind in SOURCE_SUPPORT_KINDS
        and (
            issue.block is None
            or 0 <= issue.block < len(blocks)
            and blocks[issue.block].id in changed_ids
        )
    ]
