"""Notes generation: plan globally, synthesize each topic across sources, verify, compose."""

import asyncio
from pathlib import Path

from app.notes import (
    CoursePlan,
    Inputs,
    NotesDocument,
    NotesRun,
    TopicNote,
    now,
    run_dir,
)
from app.plan import Plan
from app.syllabus import Transcript
from app.worker.artifacts import RunStore
from app.worker.composition import collect, harmonize
from app.worker.config import WorkerSettings
from app.worker.models import NotesModels
from app.worker.openrouter import Opener, OpenRouterClient
from app.worker.planning import plan_course
from app.worker.render import QuartoError, render_pdf, render_pdfs, to_quarto, topic_to_quarto
from app.worker.sources import Retriever, build_inputs
from app.worker.topics import generate_topic
from app.worker.tracing import course_trace

ACTIVE: set[str] = set()


def fail_interrupted(uploads_dir: Path) -> list[str]:
    """Runs left queued or running by a previous worker process can never finish: mark them
    failed so they can be resumed."""
    interrupted = []
    for file in uploads_dir.glob("*/notes/*/run.json"):
        run = NotesRun.model_validate_json(file.read_text())
        if run.status in ("queued", "running"):
            store = RunStore(file.parent, run)
            run.status = "failed"
            run.error = "Interrupted by a worker restart; resume the run to continue"
            store.log("failed", run.error)
            interrupted.append(f"{run.course}/{run.id}")
    return interrupted


def open_run(course_dir: Path, course: str, run_id: str, models: NotesModels) -> RunStore:
    """The store of a new run, or of an earlier run being resumed."""
    directory = run_dir(course_dir, run_id)
    previous = directory / "run.json"
    if previous.is_file():
        run = NotesRun.model_validate_json(previous.read_text())
        run.status, run.error, run.warnings = "queued", None, []
    else:
        stamp = now()
        run = NotesRun(
            id=run_id,
            course=course,
            status="queued",
            stage="queued",
            created_at=stamp,
            updated_at=stamp,
            models=models.summary(),
        )
    store = RunStore(directory, run)
    store.save()
    return store


async def topic_notes(
    client: OpenRouterClient,
    models: NotesModels,
    store: RunStore,
    plan: CoursePlan,
    inputs: Inputs,
    language: str | None,
    settings: WorkerSettings,
) -> dict[str, TopicNote]:
    """One job per topic, at most `notes_concurrency` at a time; finished topics are reused."""
    retriever = Retriever(inputs.chunks)
    gate = asyncio.Semaphore(settings.notes_concurrency)
    notes: dict[str, TopicNote] = {}
    topics = plan.topics()
    store.run.topics_total = len(topics)

    async def job(section, topic) -> None:
        name = f"topics/{topic.id}/note.json"
        done = store.read(name, TopicNote)
        if done is None or done.status == "failed":
            async with gate:
                try:
                    done = await generate_topic(
                        client,
                        models,
                        store,
                        plan,
                        section,
                        topic,
                        inputs,
                        retriever,
                        language,
                        settings.notes_revision_rounds,
                    )
                    store.write(name, done)
                except Exception as error:
                    print(f"Topic {topic.id} failed: {error!r}")
                    done = TopicNote(
                        topic_id=topic.id,
                        title=topic.title,
                        status="failed",
                        blocks=[],
                        evidence=[],
                        rounds=0,
                        verifier=None,
                        open_issues=[],
                        error=str(getattr(error, "detail", None) or error),
                    )
                    store.write(name, done)
        notes[topic.id] = done
        store.run.topics_done += 1
        store.log("topics", f"{topic.id} {topic.title}: {done.status}")

    store.run.topics_done = 0
    await asyncio.gather(*(job(section, topic) for section, topic in topics))
    return notes


async def run_notes(
    opener: Opener,
    settings: WorkerSettings,
    store: RunStore,
    plan: Plan,
    transcript: Transcript,
) -> None:
    course = store.run.course
    course_dir = settings.uploads_dir / course
    models = NotesModels.from_settings(settings)
    store.run.status = "running"
    store.run.models = models.summary()
    try:
        with course_trace(
            "generate-notes", course, {"run": store.run.id, "sessions": len(plan.sessions)}
        ) as span:
            async with opener() as client:
                store.log("inputs", "Collecting mapped chunks")
                inputs = build_inputs(settings.uploads_dir, course_dir, plan, transcript)
                store.write("inputs.json", inputs)
                for skipped in inputs.skipped:
                    store.warn(skipped)
                if not inputs.chunks:
                    raise ValueError("No session material has extractable text")
                store.log("inputs", f"{len(inputs.sources)} sources, {len(inputs.chunks)} chunks")

                course_plan = store.read("plan.json", CoursePlan)
                if course_plan is None:
                    store.log("planning", "Drafting the course plan")
                    course_plan = await plan_course(
                        client, models, store, transcript, inputs, settings.notes_plan_rounds
                    )
                store.log("planning", f"Plan ready: {len(course_plan.topics())} topics")

                notes = await topic_notes(
                    client, models, store, course_plan, inputs, transcript.language, settings
                )
                failed = [n.topic_id for n in notes.values() if n.status == "failed"]
                if failed:
                    store.warn(f"Topics failed and can be retried by resuming: {failed}")

                store.log("composition", "Harmonizing notation and cross-references")
                sections = collect(course_plan, notes)
                edits = await harmonize(client, models.consistency, course_plan, sections)
                store.log("composition", f"Applied {edits} consistency edits")

            document = NotesDocument(
                course=course,
                run=store.run.id,
                title=course_plan.title,
                created_at=now(),
                sections=sections,
                sources=inputs.sources,
                notation=course_plan.notation,
                terminology=course_plan.terminology,
                models=store.run.models,
            )
            store.write("notes.json", document)
            qmd = store.write("notes.qmd", to_quarto(document, transcript.language))
            topic_qmds = {
                store.write(
                    f"topics/{note.topic_id}/note.qmd",
                    topic_to_quarto(document, section, note, transcript.language),
                ): note.topic_id
                for section in sections
                for note in section.topics
                if note.status in ("verified", "unresolved")
            }
            store.log("rendering", "Typesetting the PDF with Quarto")
            try:
                await render_pdf(qmd, settings.quarto_bin)
                store.log("rendering", f"Typesetting {len(topic_qmds)} topic PDFs")
                failed_pdfs = await render_pdfs(
                    list(topic_qmds), settings.quarto_bin, settings.quarto_concurrency
                )
                for topic_qmd, error in failed_pdfs.items():
                    store.warn(f"PDF of {topic_qmds[topic_qmd]} not rendered: {error}")
            except QuartoError as error:
                store.warn(f"PDF not rendered: {error}")
            store.run.status = "done"
            store.log("done", "Notes are ready")
            span.update(output={"topics": len(notes), "failed": failed, "edits": edits})
    except Exception as error:
        print(f"Notes run {course}/{store.run.id} failed: {error!r}")
        store.run.status = "failed"
        store.run.error = str(getattr(error, "detail", None) or error)
        store.log("failed", store.run.error)
    finally:
        ACTIVE.discard(course)
