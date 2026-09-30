"""Book indexes: where chapters start in a PDF, and how printed page numbers map to PDF pages."""

import io
import re
from collections import Counter
from pathlib import Path
from typing import Literal

from pydantic import BaseModel
from pypdf import PdfReader, PdfWriter

from app.llm import PDF_PLUGINS, Strict, ask, chat, pdf_part
from app.openrouter import OpenRouterClient

TOC_PAGES = 30


class OutlineEntry(BaseModel):
    title: str
    level: int
    pdf_page: int  # 1-based


class BookIndex(BaseModel):
    source_sha256: str
    page_count: int
    title: str | None
    first_text: str
    method: Literal["bookmarks", "toc", "none"]
    entries: list[OutlineEntry]
    # Printed label of every PDF page, when the PDF defines page labels.
    page_labels: list[str] | None
    # pdf_page = printed_page + offset, when known without page labels.
    offset: int | None = None


def index_file(course_dir: Path, book: Path) -> Path:
    return course_dir / "index" / f"{book.name}.json"


def load_index(course_dir: Path, book: Path, digest: str) -> BookIndex | None:
    target = index_file(course_dir, book)
    if not target.is_file():
        return None
    index = BookIndex.model_validate_json(target.read_text())
    return index if index.source_sha256 == digest else None


def save_index(course_dir: Path, book: Path, index: BookIndex) -> None:
    target = index_file(course_dir, book)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(index.model_dump_json(indent=2))


def read_index(book: Path, digest: str) -> BookIndex:
    """Index from the PDF itself: bookmarks, page labels and metadata. No model calls."""
    reader = PdfReader(book)
    entries: list[OutlineEntry] = []

    def walk(items: list, level: int) -> None:
        for item in items:
            if isinstance(item, list):
                walk(item, level + 1)
                continue
            try:
                page = reader.get_destination_page_number(item)
            except Exception:
                continue
            if page is not None and page >= 0:
                entries.append(OutlineEntry(title=item.title, level=level, pdf_page=page + 1))

    try:
        walk(reader.outline, 0)
    except Exception:
        entries = []

    has_labels = "/PageLabels" in reader.trailer["/Root"]
    first_text = ""
    for page in reader.pages[:3]:
        try:
            first_text += (page.extract_text() or "") + "\n"
        except Exception:
            break
    title = reader.metadata.title if reader.metadata else None

    return BookIndex(
        source_sha256=digest,
        page_count=len(reader.pages),
        title=title or None,
        first_text=re.sub(r"\s+", " ", first_text).strip()[:1500],
        method="bookmarks" if entries else "none",
        entries=entries,
        page_labels=list(reader.page_labels) if has_labels else None,
    )


def to_pdf(index: BookIndex, printed: int) -> int | None:
    """PDF page (1-based) of a printed page number, if known."""
    if index.page_labels:
        label = str(printed)
        for i, page_label in enumerate(index.page_labels):
            if page_label == label:
                return i + 1
        return None
    if index.offset is not None:
        page = printed + index.offset
        return page if 1 <= page <= index.page_count else None
    return None


def printed_label(index: BookIndex, pdf_page: int) -> str | None:
    if index.page_labels and 1 <= pdf_page <= len(index.page_labels):
        return index.page_labels[pdf_page - 1]
    if index.offset is not None:
        return str(pdf_page - index.offset)
    return None


def printed_range(index: BookIndex, start: int, end: int) -> str | None:
    first, last = printed_label(index, start), printed_label(index, end)
    if first is None or last is None:
        return None
    return f"p. {first}" if start == end else f"pp. {first}–{last}"


def entry_end(index: BookIndex, i: int) -> int:
    """Last PDF page of outline entry i: up to the next entry at the same or a higher level.

    A new chapter starts on a fresh page, so a range ending before a top-level entry stops on
    the page before it. Sections often start mid-page, so the page they share is kept.
    """
    entry = index.entries[i]
    for following in index.entries[i + 1 :]:
        if following.level <= entry.level:
            end = following.pdf_page - 1 if following.level == 0 else following.pdf_page
            return max(end, entry.pdf_page)
    return index.page_count


def outline_text(index: BookIndex) -> str:
    """Outline lines for a prompt: id, computed position, title, printed start page."""
    lines, counters = [], []
    for i, entry in enumerate(index.entries):
        counters = counters[: entry.level + 1]
        while len(counters) <= entry.level:
            counters.append(0)
        counters[entry.level] += 1
        path = ".".join(str(c) for c in counters)
        page = printed_label(index, entry.pdf_page) or f"pdf {entry.pdf_page}"
        lines.append(f"{i} | {path} | {'  ' * entry.level}{entry.title} | page {page}")
    return "\n".join(lines)


def subset_pdf(book: Path, pages: list[int]) -> bytes:
    """A PDF with only the given 1-based pages of the book."""
    reader = PdfReader(book)
    writer = PdfWriter()
    for page in pages:
        writer.add_page(reader.pages[page - 1])
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def cut_excerpt(book: Path, start: int, end: int, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(subset_pdf(book, list(range(start, end + 1))))


def sample_pages(index: BookIndex, after: int) -> list[int]:
    count = index.page_count
    picks = {max(after + 1, round(count * f)) for f in (0.4, 0.6, 0.8)}
    return sorted(p for p in picks if after < p <= count)


# Model calls for books without bookmarks or page labels.


class TocEntry(Strict):
    title: str
    level: int
    printed_page: int | None


class PageSample(Strict):
    pdf_page: int
    printed_page: int | None


class TocExtraction(Strict):
    entries: list[TocEntry]
    samples: list[PageSample]


class OffsetExtraction(Strict):
    samples: list[PageSample]


TOC_PROMPT = """\
You read the table of contents of a book.

The attached PDF holds some pages of the book; the message says which PDF page each one is.

entries: every line of the table of contents, in order. title as printed, including its
number (e.g. "3.2 Row reduction"); level 0 for parts and chapters, 1 for sections, 2 for
subsections; printed_page: the page number the contents give for it, as an integer (null if it
is a roman numeral or missing). If these pages contain no table of contents, return [].

samples: for each sample page listed in the message, the page number printed on that page
itself (in its header or footer), or null if none is visible.
"""

OFFSET_PROMPT = """\
The attached PDF holds sample pages of a book; the message says which PDF page each one is.
samples: for each, the page number printed on the page itself (header or footer), or null.
"""


def offset_from(samples: list[PageSample]) -> int | None:
    offsets = Counter(s.pdf_page - s.printed_page for s in samples if s.printed_page is not None)
    return offsets.most_common(1)[0][0] if offsets else None


def pages_note(pages: list[int], first: int) -> str:
    listing = ", ".join(
        f"page {i} of the attachment is PDF page {p}" for i, p in enumerate(pages, 1)
    )
    return f"{listing}. Sample pages: {', '.join(str(p) for p in pages[first:])}."


async def read_toc(client: OpenRouterClient, book: Path, index: BookIndex) -> None:
    """Fill a bookmark-less index from its printed table of contents."""
    toc = list(range(1, min(TOC_PAGES, index.page_count) + 1))
    samples = [] if index.page_labels else sample_pages(index, len(toc))
    pages = toc + samples
    result = await ask(
        client,
        chat(TOC_PROMPT, pages_note(pages, len(toc)), pdf_part(book.name, subset_pdf(book, pages))),
        TocExtraction,
        "book_toc",
        PDF_PLUGINS,
        step="read-book-toc",
    )
    if not index.page_labels:
        index.offset = offset_from(result.samples)

    entries = []
    for entry in result.entries:
        if entry.printed_page is None:
            continue
        pdf_page = to_pdf(index, entry.printed_page)
        if pdf_page is not None:
            entries.append(OutlineEntry(title=entry.title, level=entry.level, pdf_page=pdf_page))
    if entries:
        index.entries = entries
        index.method = "toc"


async def read_offset(client: OpenRouterClient, book: Path, index: BookIndex) -> None:
    """Learn printed→PDF page offset from a few sample pages."""
    pages = sample_pages(index, 0)
    if not pages:
        return
    result = await ask(
        client,
        chat(OFFSET_PROMPT, pages_note(pages, 0), pdf_part(book.name, subset_pdf(book, pages))),
        OffsetExtraction,
        "page_offset",
        PDF_PLUGINS,
        step="read-page-offset",
    )
    index.offset = offset_from(result.samples)
