"""Model calls that read a book's table of contents or page numbers from its PDF."""

from collections import Counter
from pathlib import Path

from app.books import BookIndex, OutlineEntry, subset_pdf, to_pdf
from app.schemas import Strict
from app.worker.llm import PDF_PLUGINS, ask, chat, pdf_part
from app.worker.openrouter import OpenRouterClient

TOC_PAGES = 30


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
