"""Vision transcription: book pages whose PDF text loses formulas, matrices or everything (a scan)
are read once by a vision model into Markdown with LaTeX, and notes use that text instead.

Approving an excerpt starts it in the background (POST /books/transcribe); the transcripts are
cached per page next to the PDF text (see `sources.PageTranscripts`), so a run admitted later
freezes them with its inputs. For excerpts approved before, run once from api/:

    uv run python -m app.worker.vision [--uploads DIR] <course> ...
"""

import argparse
import asyncio
import sys
from pathlib import Path

from fastapi import HTTPException
from pypdf import PdfReader

from app.books import subset_pdf
from app.notes_artifacts import atomic_json
from app.plan import load_plan
from app.schemas import Strict
from app.storage import sha256
from app.worker.config import WorkerSettings
from app.worker.llm import PDF_PLUGINS, ask, chat, pdf_part
from app.worker.models import ModelSpec
from app.worker.openrouter import LONG_TIMEOUT, Opener, OpenRouterClient, openrouter_opener
from app.worker.sources import (
    PageTranscripts,
    load_transcripts,
    loses_text,
    page_texts,
    transcript_cache,
)

# Bump when PROMPT changes, so pages are read again.
PROMPT_VERSION = 1
CONCURRENCY = 4

PROMPT = """\
You transcribe one page of a textbook into Pandoc Markdown, exactly.

- Keep every word, number and symbol, in reading order. Do not solve, summarise, correct or add.
- Mathematics in LaTeX: $...$ inline, $$...$$ for display. Matrices and vectors as
  \\begin{pmatrix} (round brackets) or \\begin{bmatrix} (square), entries separated by &,
  rows by \\\\. Subscripts, superscripts, accents, bold symbols and fractions as in the book.
- Tables as Markdown tables. A figure as one line: [Figure: what it shows].
- Leave out the running header and the page number.
markdown: the page; empty if the page is blank."""


class PageTranscript(Strict):
    markdown: str


def vision_spec(settings: WorkerSettings) -> ModelSpec | None:
    model = settings.notes_vision_model.strip()
    return ModelSpec(model, effort="low", max_tokens=16000) if model else None


def cache_key(spec: ModelSpec) -> str:
    return f"{spec.model}#{PROMPT_VERSION}"


# One reader per book at a time, so concurrent jobs never lose each other's pages.
LOCKS: dict[str, asyncio.Lock] = {}


def pages_to_read(
    course_dir: Path, book: Path, digest: str, spans: list[tuple[int, int]], done: set[int]
) -> list[int]:
    reader = PdfReader(book)
    wanted = []
    for first, last in spans:
        texts = page_texts(course_dir, book, digest, first, last)
        wanted += [
            page
            for page, text in texts.items()
            if page not in done and loses_text(reader.pages[page - 1], text)
        ]
    return sorted(set(wanted))


async def transcribe_pages(
    client: OpenRouterClient,
    spec: ModelSpec,
    course_dir: Path,
    book: Path,
    spans: list[tuple[int, int]],
) -> tuple[int, list[int]]:
    """Transcribe the pages of `spans` that `loses_text` and have no transcript from this model
    and prompt. Returns how many were read, and the pages whose call failed (read next time)."""
    digest = await asyncio.to_thread(sha256, book)
    async with LOCKS.setdefault(digest, asyncio.Lock()):
        cached = load_transcripts(course_dir, digest)
        if cached is None or cached.key != cache_key(spec):
            cached = PageTranscripts(source_sha256=digest, key=cache_key(spec), pages={})
        todo = await asyncio.to_thread(
            pages_to_read, course_dir, book, digest, spans, set(cached.pages)
        )
        gate = asyncio.Semaphore(CONCURRENCY)
        failed: list[int] = []

        async def read(page: int) -> None:
            pdf = await asyncio.to_thread(subset_pdf, book, [page])
            async with gate:
                try:
                    result = await ask(
                        client,
                        chat(
                            PROMPT,
                            f"PDF page {page} of {book.name}.",
                            pdf_part(f"{book.stem}-p{page}.pdf", pdf),
                        ),
                        PageTranscript,
                        "page_transcript",
                        PDF_PLUGINS,
                        step="transcribe-page",
                        spec=spec,
                    )
                except HTTPException as error:
                    print(f"Can't transcribe {book.name} p. {page}: {error.detail}")
                    failed.append(page)
                    return
            cached.pages[page] = result.markdown

        await asyncio.gather(*(read(page) for page in todo))
        if len(todo) > len(failed):
            target = transcript_cache(course_dir, digest)
            await asyncio.to_thread(atomic_json, target, cached.model_dump(mode="json"))
    return len(todo) - len(failed), sorted(failed)


async def transcribe_excerpts(
    client: OpenRouterClient, spec: ModelSpec, course_dir: Path
) -> dict[str, tuple[int, list[int]]]:
    """Transcribe the pages of every approved excerpt of the course that need it."""
    plan = load_plan(course_dir)
    spans: dict[str, list[tuple[int, int]]] = {}
    for p in plan.proposals:
        if p.status == "approved" and p.pdf_start is not None and p.pdf_end is not None:
            spans.setdefault(p.book, []).append((p.pdf_start, p.pdf_end))
    result = {}
    for path, book_spans in sorted(spans.items()):
        book = course_dir.parent / path
        if book.suffix.lower() == ".pdf" and book.is_file():
            result[path] = await transcribe_pages(client, spec, course_dir, book, book_spans)
    return result


# Courses being transcribed, and those whose excerpts changed meanwhile.
ACTIVE: set[str] = set()
AGAIN: set[str] = set()


async def keep_transcribing(opener: Opener, spec: ModelSpec, uploads_dir: Path, course: str):
    """Transcribe a course's excerpts; a request that comes meanwhile runs once more after."""
    if course in ACTIVE:
        AGAIN.add(course)
        return
    ACTIVE.add(course)
    try:
        while True:
            AGAIN.discard(course)
            try:
                async with opener() as client:
                    result = await transcribe_excerpts(client, spec, uploads_dir / course)
                read = sum(n for n, _ in result.values())
                failed = sum(len(f) for _, f in result.values())
                print(f"Transcribed {course}: {read} pages, {failed} failed")
            except Exception as error:
                print(f"Transcribing {course} failed: {error!r}")
            if course not in AGAIN:
                break
    finally:
        ACTIVE.discard(course)


async def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Transcribe the approved excerpts' pages.")
    parser.add_argument("courses", nargs="+")
    parser.add_argument("--uploads", type=Path)
    args = parser.parse_args(argv)
    settings = WorkerSettings()
    uploads = args.uploads or settings.uploads_dir
    spec = vision_spec(settings)
    if spec is None or not settings.openrouter_api_key:
        print("Set OPENROUTER_API_KEY and NOTES_VISION_MODEL first", file=sys.stderr)
        return 1
    async with openrouter_opener(settings, LONG_TIMEOUT)() as client:
        for course in args.courses:
            for book, (read, failed) in (
                await transcribe_excerpts(client, spec, uploads / course)
            ).items():
                note = f", failed pages {failed}" if failed else ""
                print(f"{book}: {read} pages transcribed{note}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
