"""Map materials: match citations to uploaded books, then locate the cited pages in each book."""

import asyncio
from dataclasses import dataclass
from pathlib import Path

from app.books import (
    BookIndex,
    entry_end,
    load_index,
    outline_text,
    printed_range,
    read_index,
    read_offset,
    read_toc,
    save_index,
    to_pdf,
)
from app.llm import Strict, ask, chat
from app.openrouter import OpenRouterClient
from app.plan import BookMatch, Plan, Proposal, new_id
from app.storage import sha256
from app.syllabus import SessionReading, Transcript


@dataclass
class Target:
    """A session reading that cites pages of a book."""

    session_id: str
    reading: SessionReading


@dataclass
class Book:
    path: str  # relative to the uploads dir
    file: Path
    index: BookIndex


# Matching citations to files.


class Match(Strict):
    item: int
    file: int | None


class BookMatches(Strict):
    materials: list[Match]
    citations: list[Match]


MATCH_PROMPT = """\
You match a course's reading list to the book files a lecturer uploaded.

You get course materials (M0, M1, ...), loose citations (C0, C1, ...) and files (F0, F1, ...)
with their filename, PDF title and the text of their first pages. For every material and every
citation, return the number of the file that contains that same work (same title and authors;
any edition or language version), or null when no file does. Several items may match one file.
Videos, websites and articles that are not among the files are null.
"""


def match_prompt(materials: list[str], citations: list[str], books: list[Book]) -> str:
    lines = ["Course materials:"]
    lines += [f"M{i}: {raw}" for i, raw in enumerate(materials)] or ["(none)"]
    lines += ["", "Loose citations:"]
    lines += [f"C{i}: {raw}" for i, raw in enumerate(citations)] or ["(none)"]
    lines += ["", "Files:"]
    for i, book in enumerate(books):
        lines.append(
            f"F{i}: filename {book.file.name!r}; PDF title {book.index.title!r}; "
            f"first pages: {book.index.first_text[:600]!r}"
        )
    return "\n".join(lines)


async def match_books(
    client: OpenRouterClient, materials: list[str], citations: list[str], books: list[Book]
) -> tuple[dict[int, str | None], dict[int, str | None]]:
    if not books or not (materials or citations):
        return {}, {}
    result = await ask(
        client,
        chat(MATCH_PROMPT, match_prompt(materials, citations, books)),
        BookMatches,
        "book_match",
    )

    def pick(matches: list[Match], count: int) -> dict[int, str | None]:
        return {
            m.item: books[m.file].path if m.file is not None and 0 <= m.file < len(books) else None
            for m in matches
            if 0 <= m.item < count
        }

    return pick(result.materials, len(materials)), pick(result.citations, len(citations))


# Locating pages.


class RangeOut(Strict):
    start_entry: int | None
    end_entry: int | None
    printed_start: int | None
    printed_end: int | None
    label: str


class ReadingRanges(Strict):
    reading: int
    ranges: list[RangeOut]
    note: str | None


class RangesOut(Strict):
    readings: list[ReadingRanges]


RANGES_PROMPT = """\
You locate the chapters and pages that readings cite in a book.

You get the book's outline, one line per entry: id | position | title | printed start page,
and readings (R0, R1, ...) that cite this book. For each reading, return the parts of the book
it cites as ranges:
- A range covers outline entries start_entry through end_entry, inclusive, by id. For one
  section set both to its id; for "Chapter 1.1-1.3" use the ids of 1.1 and 1.3.
- When the citation gives explicit page numbers, put them in printed_start / printed_end as
  integers. They replace the outline boundary on that side: "Chapter 1.3 (p. 12-15)" is
  printed_start 12, printed_end 15; "Chapter 1.1-1.3 (to p. 15)" is start_entry of 1.1 and
  printed_end 15; "p. 45" is printed_start 45 and printed_end 45.
- Chapter and section numbers in citations follow the book's own numbering. The position
  column is computed from the order of the outline and usually, not always, matches it; a
  number inside the title is authoritative.
- Adjacent parts form one range. Use separate ranges only for parts that are apart, e.g.
  "ch. 3, 7".
- label: a short description of the range as cited, e.g. "Ch. 1.1-1.3 (to p. 15)".
- Leave out any part you cannot find and say so in note. Set unused fields to null.
"""


def ranges_prompt(book: Book, title: str, targets: list[Target]) -> str:
    lines = [f"Book: {title}", "", "Outline:", outline_text(book.index), "", "Readings:"]
    for i, target in enumerate(targets):
        lines.append(f"R{i}: {target.reading.raw} (cited parts: {target.reading.pages})")
    return "\n".join(lines)


def resolve(index: BookIndex, r: RangeOut) -> tuple[int, int, bool] | None:
    """PDF start and end page of a range, and whether printed pages were used."""
    count = len(index.entries)

    def valid(i: int | None) -> bool:
        return i is not None and 0 <= i < count

    if r.printed_start is not None:
        start = to_pdf(index, r.printed_start)
    elif valid(r.start_entry):
        start = index.entries[r.start_entry].pdf_page
    else:
        start = None

    last = r.end_entry if valid(r.end_entry) else r.start_entry
    if r.printed_end is not None:
        end = to_pdf(index, r.printed_end)
    elif valid(last):
        end = entry_end(index, last)
    else:
        end = start if r.printed_start is not None else None

    if start is None or end is None or end < start:
        return None
    return start, end, r.printed_start is not None or r.printed_end is not None


def needs_offset(index: BookIndex, result: RangesOut) -> bool:
    if index.page_labels or index.offset is not None:
        return False
    return any(
        r.printed_start is not None or r.printed_end is not None
        for reading in result.readings
        for r in reading.ranges
    )


def proposals_for(
    book: Book, target: Target, ranges: list[RangeOut], note: str | None
) -> list[Proposal]:
    index = book.index
    resolved = []
    for r in ranges:
        hit = resolve(index, r)
        if hit:
            resolved.append((*hit, r.label))
    resolved.sort()

    merged: list[list] = []
    for start, end, printed, label in resolved:
        if merged and start <= merged[-1][1] + 1:
            merged[-1][1] = max(merged[-1][1], end)
            merged[-1][2] = merged[-1][2] or printed
            merged[-1][3] = f"{merged[-1][3]}; {label}"
        else:
            merged.append([start, end, printed, label])

    base = {"session_id": target.session_id, "reading": target.reading.raw, "book": book.path}
    if not merged:
        return [
            Proposal(
                id=new_id(),
                **base,
                label=target.reading.pages or target.reading.raw,
                pdf_start=None,
                pdf_end=None,
                printed=None,
                method="manual" if index.method == "none" else index.method,
                note=note or "Couldn't find these pages in the book; enter them by hand.",
            )
        ]
    return [
        Proposal(
            id=new_id(),
            **base,
            label=label,
            pdf_start=start,
            pdf_end=end,
            printed=printed_range(index, start, end),
            method="pages" if printed else index.method,
            note=note,
        )
        for start, end, printed, label in merged
    ]


async def map_book(
    client: OpenRouterClient, course_dir: Path, book: Book, title: str, targets: list[Target]
) -> list[Proposal]:
    index = book.index
    if index.method == "none":
        await read_toc(client, book.file, index)
        save_index(course_dir, book.file, index)
    if index.method == "none":
        note = "No bookmarks or table of contents found in this book; enter the pages by hand."
        return [p for t in targets for p in proposals_for(book, t, [], note)]

    result = await ask(
        client,
        chat(RANGES_PROMPT, ranges_prompt(book, title, targets)),
        RangesOut,
        "reading_ranges",
    )
    if needs_offset(index, result):
        await read_offset(client, book.file, index)
        save_index(course_dir, book.file, index)

    by_reading = {r.reading: r for r in result.readings}
    proposals = []
    for i, target in enumerate(targets):
        found = by_reading.get(i)
        if found:
            proposals += proposals_for(book, target, found.ranges, found.note)
        else:
            proposals += proposals_for(book, target, [], None)
    return proposals


# The whole run.


def load_books(uploads_dir: Path, course_dir: Path, paths: list[str]) -> list[Book]:
    books = []
    for path in paths:
        file = uploads_dir / path
        if file.suffix.lower() != ".pdf" or not file.is_file():
            continue
        digest = sha256(file)
        index = load_index(course_dir, file, digest)
        if index is None:
            try:
                index = read_index(file, digest)
            except Exception as error:
                print(f"Can't read book {path}: {error!r}")
                continue
            save_index(course_dir, file, index)
        books.append(Book(path=path, file=file, index=index))
    return books


async def run_mapping(
    client: OpenRouterClient,
    uploads_dir: Path,
    course_dir: Path,
    plan: Plan,
    transcript: Transcript,
    reading_paths: list[str],
) -> tuple[list[BookMatch], list[Proposal]]:
    """Book matches for the course materials, and fresh page proposals for session readings."""
    books = load_books(uploads_dir, course_dir, reading_paths)
    materials = [m.raw for m in transcript.learning_materials]
    confirmed = {b.material: b for b in plan.books if b.confirmed}
    confirmed = {i: b for i, b in confirmed.items() if i < len(materials) and b.raw == materials[i]}

    targets: list[Target] = []
    for entry, session in zip(plan.sessions, transcript.sessions, strict=True):
        for reading in session.required_readings + session.optional_readings:
            if reading.pages:
                targets.append(Target(session_id=entry.id, reading=reading))
    loose = [t for t in targets if t.reading.material_ref is None]
    loose_number = {id(t): i for i, t in enumerate(loose)}

    material_files, loose_files = await match_books(
        client, materials, [t.reading.raw for t in loose], books
    )
    matches = [
        confirmed.get(i) or BookMatch(material=i, raw=raw, file=material_files.get(i))
        for i, raw in enumerate(materials)
    ]

    by_book: dict[str, list[Target]] = {}
    for target in targets:
        ref = target.reading.material_ref
        path = matches[ref].file if ref is not None else loose_files.get(loose_number[id(target)])
        if path:
            by_book.setdefault(path, []).append(target)

    titles = {m.file: m.raw for m in matches if m.file}
    jobs = [
        map_book(
            client, course_dir, book, titles.get(book.path, book.file.name), by_book[book.path]
        )
        for book in books
        if book.path in by_book
    ]
    proposals = [p for batch in await asyncio.gather(*jobs) for p in batch]
    return matches, proposals


def merge_proposals(plan: Plan, fresh: list[Proposal]) -> None:
    """Replace open proposals with fresh ones; never touch approved or rejected ones."""
    kept = [p for p in plan.proposals if p.status != "proposed"]
    decided = {(p.session_id, p.reading, p.book) for p in kept}
    plan.proposals = kept + [p for p in fresh if (p.session_id, p.reading, p.book) not in decided]
