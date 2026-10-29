"""Mapped chunks: the text of every session material, cut into chunks with stable ids."""

import math
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import mammoth
from pydantic import BaseModel
from pypdf import PdfReader

from app.books import load_index, printed_label
from app.notes import Chunk, Inputs, Source
from app.plan import Plan
from app.storage import sha256
from app.syllabus import Transcript

CHUNK_CHARS = 1400
MAX_PAGES = 600
TEXT_SUFFIXES = {".txt", ".md", ".qmd", ".tex"}
# Characters of text below which a page counts as having none: a scan, or a blank page.
NEAR_EMPTY = 40


def page_ranges(pages: list[int]) -> str:
    """Sorted page numbers as "PDF page 3" or "PDF pages 3, 7–9"."""
    spans: list[list[int]] = []
    for page in pages:
        if spans and page == spans[-1][1] + 1:
            spans[-1][1] = page
        else:
            spans.append([page, page])
    text = ", ".join(str(a) if a == b else f"{a}–{b}" for a, b in spans)
    return f"PDF page {text}" if len(pages) == 1 else f"PDF pages {text}"


class PageTexts(BaseModel):
    source_sha256: str
    count: int
    pages: dict[int, str]


def text_cache(course_dir: Path, digest: str) -> Path:
    return course_dir / "text" / f"{digest[:16]}.pages.json"


def page_texts(
    course_dir: Path, file: Path, digest: str, first: int = 1, last: int | None = None
) -> dict[int, str]:
    """Text of PDF pages first..last (a whole PDF up to MAX_PAGES), or of a whole non-PDF file
    as page 1. Only missing pages are extracted; the cache is keyed by the file's hash."""
    suffix = file.suffix.lower()
    if suffix == ".docx":
        with file.open("rb") as f:
            return {1: mammoth.extract_raw_text(f).value}
    if suffix in TEXT_SUFFIXES:
        return {1: file.read_text(errors="replace")}
    if suffix != ".pdf":
        return {}

    cache = text_cache(course_dir, digest)
    cached = PageTexts.model_validate_json(cache.read_text()) if cache.is_file() else None
    reader = None
    if cached is None or cached.source_sha256 != digest:
        reader = PdfReader(file)
        cached = PageTexts(source_sha256=digest, count=len(reader.pages), pages={})
    end = min(last, cached.count) if last else min(cached.count, MAX_PAGES)
    wanted = range(first, end + 1)
    missing = [page for page in wanted if page not in cached.pages]
    if missing or not cache.is_file():
        reader = reader or PdfReader(file)
        for page in missing:
            try:
                cached.pages[page] = reader.pages[page - 1].extract_text() or ""
            except Exception:
                cached.pages[page] = ""
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(cached.model_dump_json())
    return {page: cached.pages[page] for page in wanted}


# Pages whose PDF text loses what is on them. Typeset matrices come out as stacked bracket
# pieces with their entries run together, and TeX math fonts lose symbols (≠ becomes =).
BRACKETS = re.compile("[⎛⎜⎝⎞⎟⎠⎡⎢⎣⎤⎥⎦]")
MATH_FONT = re.compile(
    r"CMMI|CMSY|CMEX|CMBSY|MSAM|MSBM|EUFM|EUSM|RSFS|MTMI|MTSY|MTEX|MathematicalPi|LMMath|"
    r"txsy|txmi|pxsy|pxmi|STIX\w*Math|Cambria.?Math",
    re.IGNORECASE,
)


def font_names(resources, depth: int = 0) -> set[str]:
    """Base fonts of a page's resources, those of its form XObjects included."""
    if resources is None or depth > 3:
        return set()
    resources = resources.get_object()
    names = {
        str(f.get_object().get("/BaseFont", "")) for f in (resources.get("/Font") or {}).values()
    }
    for item in (resources.get("/XObject") or {}).values():
        item = item.get_object()
        if item.get("/Subtype") == "/Form":
            names |= font_names(item.get("/Resources"), depth + 1)
    return names


def loses_text(page, text: str) -> bool:
    """Whether a page's PDF text misses what the page shows: it has no text (a scan), typeset
    matrices or math set in TeX fonts."""
    if len(text.strip()) < NEAR_EMPTY or BRACKETS.search(text):
        return True
    try:
        return any(MATH_FONT.search(name) for name in font_names(page.get("/Resources")))
    except Exception:
        return False


class PageTranscripts(BaseModel):
    """Pages of a PDF a vision model transcribed to Markdown with LaTeX, in place of their PDF
    text (see `app.worker.vision`). `key` names the model and prompt that read them."""

    source_sha256: str
    key: str
    pages: dict[int, str]


def transcript_cache(course_dir: Path, digest: str) -> Path:
    return course_dir / "text" / f"{digest[:16]}.vision.json"


def load_transcripts(course_dir: Path, digest: str) -> PageTranscripts | None:
    target = transcript_cache(course_dir, digest)
    if not target.is_file():
        return None
    try:
        transcripts = PageTranscripts.model_validate_json(target.read_text())
    except ValueError:
        return None
    return transcripts if transcripts.source_sha256 == digest else None


def untranscribed(file: Path, pages: dict[int, str], transcribed: dict[int, str]) -> list[int]:
    """Pages with text that `loses_text` and no transcription. Pages without text are reported
    on their own."""
    reader = PdfReader(file)
    return [
        page
        for page, text in pages.items()
        if page not in transcribed
        and len(text.strip()) >= NEAR_EMPTY
        and loses_text(reader.pages[page - 1], text)
    ]


def split_text(text: str) -> list[str]:
    """Pieces of at most CHUNK_CHARS, cut at line ends where possible."""
    pieces, current = [], ""
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        while len(line) > CHUNK_CHARS:
            if current:
                pieces.append(current)
                current = ""
            pieces.append(line[:CHUNK_CHARS])
            line = line[CHUNK_CHARS:]
        if current and len(current) + len(line) + 1 > CHUNK_CHARS:
            pieces.append(current)
            current = ""
        current = f"{current}\n{line}" if current else line
    if current:
        pieces.append(current)
    return pieces


@dataclass
class Material:
    file: str
    title: str
    label: str | None
    pdf_start: int | None
    pdf_end: int | None


def session_materials(plan: Plan, transcript: Transcript) -> list[tuple[Material, int]]:
    """Every file attached to a session; excerpts point at their book's page range."""
    excerpts = {p.excerpt: p for p in plan.proposals if p.excerpt}
    titles = {b.file: b.raw for b in plan.books if b.file}
    found = []
    for number, (entry, _) in enumerate(zip(plan.sessions, transcript.sessions, strict=True)):
        for path in entry.files:
            proposal = excerpts.get(path)
            if proposal and proposal.pdf_start is not None and proposal.pdf_end is not None:
                material = Material(
                    file=proposal.book,
                    title=titles.get(proposal.book, Path(proposal.book).name),
                    label=proposal.label,
                    pdf_start=proposal.pdf_start,
                    pdf_end=proposal.pdf_end,
                )
            else:
                material = Material(
                    file=path, title=Path(path).name, label=None, pdf_start=None, pdf_end=None
                )
            found.append((material, number))
    return found


def build_inputs(uploads_dir: Path, course_dir: Path, plan: Plan, transcript: Transcript) -> Inputs:
    sources: list[Source] = []
    chunks: dict[str, Chunk] = {}
    by_key: dict[tuple, Source] = {}
    skipped: list[str] = []

    for material, session in session_materials(plan, transcript):
        key = (material.file, material.pdf_start, material.pdf_end)
        if key in by_key:
            if session not in by_key[key].sessions:
                by_key[key].sessions.append(session)
            continue

        file = uploads_dir / material.file
        if not file.is_file():
            skipped.append(f"{material.file}: file is missing")
            continue
        digest = sha256(file)
        try:
            pages = page_texts(course_dir, file, digest, material.pdf_start or 1, material.pdf_end)
        except Exception as error:
            print(f"Can't read {material.file}: {error!r}")
            skipped.append(f"{material.file}: could not read the text")
            continue

        is_pdf = file.suffix.lower() == ".pdf"
        garbled: list[int] = []
        if is_pdf:
            read = load_transcripts(course_dir, digest)
            transcribed = read.pages if read else {}
            if material.pdf_start is not None:
                garbled = untranscribed(file, pages, transcribed)
            pages = {page: transcribed.get(page, text) for page, text in pages.items()}
        index = load_index(course_dir, file, digest) if is_pdf else None
        first = material.pdf_start or 1
        last = material.pdf_end or max(pages, default=0)
        source = Source(
            id=len(sources),
            file=material.file,
            title=material.title,
            label=material.label,
            pdf_start=material.pdf_start,
            pdf_end=material.pdf_end,
            sessions=[session],
            outline=[
                e.title for e in (index.entries if index else []) if first <= e.pdf_page <= last
            ],
            chunk_ids=[],
        )
        for page, text in pages.items():
            for n, piece in enumerate(split_text(text)):
                chunk_id = f"{digest[:8]}-p{page}-{n}" if is_pdf else f"{digest[:8]}-{n}"
                source.chunk_ids.append(chunk_id)
                chunks.setdefault(
                    chunk_id,
                    Chunk(
                        id=chunk_id,
                        source=source.id,
                        file=material.file,
                        pdf_page=page if is_pdf else None,
                        printed_page=printed_label(index, page) if index else None,
                        text=piece,
                    ),
                )
        if not source.chunk_ids:
            skipped.append(f"{material.file}: no extractable text (scanned or unsupported)")
            continue
        blank = [page for page, text in pages.items() if len(text.strip()) < NEAR_EMPTY]
        if is_pdf and material.pdf_start is not None and blank:
            skipped.append(
                f"{material.file}: {page_ranges(blank)} of {material.label or 'the excerpt'} "
                f"{'has' if len(blank) == 1 else 'have'} no extractable text (scanned or blank); "
                "the notes miss what is on them"
            )
        if garbled:
            skipped.append(
                f"{material.file}: {page_ranges(garbled)} of {material.label or 'the excerpt'} "
                f"{'has' if len(garbled) == 1 else 'have'} formulas or matrices their PDF text "
                "garbles, and no vision transcription yet; the notes may misread them"
            )
        by_key[key] = source
        sources.append(source)

    return Inputs(sources=sources, chunks=list(chunks.values()), skipped=skipped)


TOKEN = re.compile(r"\w{2,}", re.UNICODE)


def tokens(text: str) -> list[str]:
    return [t.casefold() for t in TOKEN.findall(text)]


class Retriever:
    """BM25 over chunk text: the retrieval index the evidence selector draws candidates from."""

    def __init__(self, chunks: list[Chunk], k1: float = 1.4, b: float = 0.75) -> None:
        self.chunks = chunks
        self.k1, self.b = k1, b
        self.terms = [Counter(tokens(c.text)) for c in chunks]
        self.lengths = [sum(t.values()) for t in self.terms]
        self.average = sum(self.lengths) / len(self.lengths) if chunks else 0
        frequency = Counter(term for t in self.terms for term in t)
        count = len(chunks)
        self.idf = {
            term: math.log(1 + (count - df + 0.5) / (df + 0.5)) for term, df in frequency.items()
        }

    def score(self, i: int, query: list[str]) -> float:
        terms, length = self.terms[i], self.lengths[i]
        total = 0.0
        for term in query:
            tf = terms.get(term)
            if tf:
                norm = tf + self.k1 * (1 - self.b + self.b * length / (self.average or 1))
                total += self.idf[term] * tf * (self.k1 + 1) / norm
        return total

    def search(self, query: str, limit: int, within: set[str] | None = None) -> list[Chunk]:
        words = list(dict.fromkeys(tokens(query)))
        scored = [
            (self.score(i, words), i)
            for i, chunk in enumerate(self.chunks)
            if within is None or chunk.id in within
        ]
        ranked = sorted((s for s in scored if s[0] > 0), key=lambda s: (-s[0], s[1]))
        return [self.chunks[i] for _, i in ranked[:limit]]
