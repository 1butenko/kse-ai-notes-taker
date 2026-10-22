"""Manual topic edits and restores: one short run-lock transaction each, never a model call."""

import asyncio
from collections.abc import Callable
from pathlib import Path

from fastapi import HTTPException, status

from app.notes_revisions import (
    EditResult,
    InvalidEdit,
    RevisionConflict,
    RevisionNotFound,
    RevisionStore,
    RevisionView,
    TopicPatch,
)


async def transact(change: Callable[[], RevisionView]) -> EditResult:
    """Wait for the blocking run lock in a thread, so the event loop keeps serving."""
    try:
        view = await asyncio.to_thread(change)
    except RevisionConflict as error:
        raise HTTPException(status.HTTP_409_CONFLICT, str(error)) from error
    except RevisionNotFound as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(error)) from error
    except InvalidEdit as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error)) from error
    # Rendering new revisions comes later; existing artifacts keep their own revision.
    return EditResult(revision=view.info, render=None)


async def revise(directory: Path, topic: str, patch: TopicPatch) -> EditResult:
    return await transact(lambda: RevisionStore(directory).commit_topic(topic, patch))


async def restore(directory: Path, revision: int, base_revision: int) -> EditResult:
    return await transact(lambda: RevisionStore(directory).restore(revision, base_revision))
