"""Notes generation: plan globally, synthesize each topic across sources, verify, compose."""

import asyncio
import json
from pathlib import Path

from app.note_assets import asset_resources
from app.notes import (
    CoursePlan,
    Inputs,
    NotesDocument,
    NotesRun,
    NotesSection,
    RenderedArtifact,
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
from app.worker.quarto import QuartoError, render_document
from app.worker.references import ReferenceContext
from app.worker.render import to_quarto, topic_to_quarto
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
                inputs = await asyncio.to_thread(
                    build_inputs, settings.uploads_dir, course_dir, plan, transcript
                )
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
                schema_version=2,
                language=transcript.language if transcript.language in ("uk", "en") else None,
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
            await render_notes_outputs(document, store, settings)
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


async def render_notes_outputs(
    document: NotesDocument, store: RunStore, settings: WorkerSettings
) -> list[RenderedArtifact]:
    """Save format sources and a manifest even when individual renders fail.

    The run directory is the artifacts root. Revision zero keeps the established
    notes.pdf/notes.qmd and topics/<id>/note.pdf download locations.
    """
    artifacts: list[RenderedArtifact] = []
    gate = asyncio.Semaphore(settings.quarto_concurrency)
    store.log("rendering", "Rendering HTML and PDF with Quarto")
    store.write("artifacts.json", "[]")

    async def one(section: NotesSection | None = None, note: TopicNote | None = None):
        prefix = f"topics/{note.topic_id}/" if note else ""
        stem = "note" if note else "notes"
        prepared = {}
        resources = {}
        context = ReferenceContext(public_api_url=settings.public_api_url)
        results = []
        for target in ("html", "pdf"):
            try:
                source = (
                    topic_to_quarto(document, section, note, document.language, target, context)
                    if note
                    else to_quarto(document, document.language, target, context)
                )
                resources.update(asset_resources(store.directory, document.assets, source))
                name = (
                    f"{prefix}{stem}.qmd"
                    if target == "pdf"
                    else (f"{prefix}sources/html/{stem}.qmd")
                )
                prepared[target] = store.write(name, source)
            except (QuartoError, OSError, ValueError) as error:
                results.append(
                    RenderedArtifact(
                        format=target,
                        path=f"{stem}.{target}",
                        revision=0,
                        status="failed",
                        error=str(error),
                    )
                )
        async with gate:
            results += await render_document(
                prepared, store.directory / prefix, 0, settings.quarto_bin, resources=resources
            )
        for artifact in results:
            artifact.path = prefix + artifact.path
            artifact.topic_id = note.topic_id if note else None
            if artifact.status == "failed":
                label = artifact.format.upper() + (f" of {note.topic_id}" if note else "")
                store.warn(f"{label} not rendered: {artifact.error}")
        artifacts.extend(results)
        store.write("artifacts.json", json.dumps([a.model_dump() for a in artifacts], indent=2))

    await one()
    await asyncio.gather(
        *(
            one(section, note)
            for section in document.sections
            for note in section.topics
            if note.status in ("verified", "unresolved")
        )
    )
    return artifacts
