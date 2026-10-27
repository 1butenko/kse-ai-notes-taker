"""Lecture notes: each course's queue of lectures, written one at a time, and Stop."""

import asyncio
from pathlib import Path

from app.notes import (
    RUN_ID,
    LectureQueue,
    NotesRun,
    QueueItem,
    load_queue,
    new_run_id,
    queue_file,
    run_dir,
)
from app.notes_revisions import RevisionConflict
from app.plan import Plan, UnknownSession, aligned, scope_to_session
from app.syllabus import Transcript
from app.worker.artifacts import RunStore
from app.worker.config import WorkerSettings
from app.worker.models import NotesModels
from app.worker.notes import ACTIVE, mark_stopped, open_run, run_notes
from app.worker.openrouter import Opener

# The run task being written per course, so Stop can cancel it.
TASKS: dict[str, asyncio.Task] = {}
# The queue of each course with a job; queue.json mirrors it for the API.
QUEUES: dict[str, LectureQueue] = {}
# Courses whose job was asked to stop; nothing more of theirs starts.
STOPPING: set[str] = set()

Admitted = tuple[RunStore, Plan, Transcript]


class NoReadings(Exception):
    pass


def save_queue(course_dir: Path, queue: LectureQueue) -> None:
    target = queue_file(course_dir)
    if not queue.waiting and queue.active is None:
        target.unlink(missing_ok=True)
        return
    partial = target.with_name(f".{target.name}.partial")
    partial.write_text(queue.model_dump_json(indent=2))
    partial.replace(target)


def admit(settings: WorkerSettings, course: str, item: QueueItem) -> Admitted:
    """Open the run of one lecture from the course plan as it is on disk now."""
    plan, transcript, _ = aligned(settings.uploads_dir, course)
    if transcript is None:
        raise UnknownSession("The course has no syllabus")
    scoped, syllabus = scope_to_session(plan, transcript, item.session_id)
    if not scoped.sessions[0].files:
        raise NoReadings("Add readings to this lecture first")
    course_dir = settings.uploads_dir / course
    models = NotesModels.from_settings(settings)
    if item.resume:
        try:
            store = open_run(
                course_dir, course, item.resume, models, scoped, syllabus, item.session_id
            )
            return store, scoped, syllabus
        except RevisionConflict:
            if not item.renew:
                raise
            print(f"Lecture {course}/{item.session_id}: readings changed, writing a new run")
    store = open_run(course_dir, course, new_run_id(), models, scoped, syllabus, item.session_id)
    return store, scoped, syllabus


async def drain(
    opener: Opener, settings: WorkerSettings, course: str, admitted: Admitted | None
) -> None:
    """Write the admitted run, then each waiting lecture in turn, until done or stopped.

    The course stays in ACTIVE throughout, so no other job of it can start.
    """
    course_dir = settings.uploads_dir / course
    queue = QUEUES.setdefault(course, LectureQueue())
    try:
        while admitted is not None:
            store, plan, transcript = admitted
            admitted = None
            if course in STOPPING:
                mark_stopped(store)
                break
            queue.active, queue.active_session = store.run.id, store.run.session_id
            save_queue(course_dir, queue)
            task = asyncio.create_task(run_notes(opener, settings, store, plan, transcript))
            TASKS[course] = task
            try:
                await task
            except asyncio.CancelledError:
                pass  # Stopped before it began; recorded below.
            current = asyncio.current_task()
            if current and current.cancelling():
                raise asyncio.CancelledError
            if store.run.status in ("queued", "running"):
                mark_stopped(store)
            queue.active = queue.active_session = None
            while admitted is None and queue.waiting and course not in STOPPING:
                item = queue.waiting.pop(0)
                save_queue(course_dir, queue)
                try:
                    admitted = await asyncio.to_thread(admit, settings, course, item)
                except (LookupError, NoReadings, RevisionConflict, OSError, ValueError) as error:
                    print(f"Skipped lecture {course}/{item.session_id}: {error}")
    finally:
        TASKS.pop(course, None)
        QUEUES.pop(course, None)
        STOPPING.discard(course)
        save_queue(course_dir, LectureQueue())
        ACTIVE.discard(course)


def stop(settings: WorkerSettings, course: str) -> LectureQueue:
    """Empty the course's queue and cancel the run being written; it stays resumable."""
    course_dir = settings.uploads_dir / course
    if course not in ACTIVE:
        save_queue(course_dir, LectureQueue())
        return LectureQueue()
    STOPPING.add(course)
    queue = QUEUES.setdefault(course, LectureQueue())
    queue.waiting.clear()
    save_queue(course_dir, queue)
    task = TASKS.get(course)
    if task and not task.done():
        task.cancel()
    return queue


def drop_queues(uploads_dir: Path) -> list[str]:
    """At startup: a queue left by a previous worker process is dropped, with a warning on
    the run it was writing (failed by `fail_interrupted`)."""
    dropped = []
    for file in sorted(uploads_dir.glob("*/queue.json")):
        queue = load_queue(file.parent)
        waiting = len(queue.waiting)
        active = queue.active if queue.active and RUN_ID.match(queue.active) else None
        target = run_dir(file.parent, active) / "run.json" if active else None
        if waiting and target and target.is_file():
            try:
                run = NotesRun.model_validate_json(target.read_text())
                lectures = "lecture was" if waiting == 1 else "lectures were"
                RunStore(target.parent, run).warn(
                    f"{waiting} queued {lectures} dropped by a worker restart; "
                    "Generate all queues them again"
                )
            except (OSError, ValueError):
                pass
        file.unlink(missing_ok=True)
        dropped.append(file.parent.name)
    return dropped
