"""A small course on disk for tests: a syllabus, a book with an excerpt, and a handout."""

from pathlib import Path

from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from app.plan import BookMatch, Plan, PlanSession, Proposal
from app.syllabus import Session, Transcript
from tests.test_plans import put, put_plan, put_transcript

BOOK_PAGES = [
    "Chapter 1 Linear systems. Gaussian elimination reduces a linear system to echelon form.",
    "Row operations do not change the solution set of a linear system.",
    "Chapter 2 Vector spaces. A vector space is a set with addition and scalar multiplication.",
    "A basis of a vector space is a linearly independent spanning set.",
]


def text_pdf(path: Path, pages: list[str]) -> None:
    """A PDF with one line of real text per page, printed page labels starting at 10."""
    writer = PdfWriter()
    font = writer._add_object(
        DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Helvetica"),
            }
        )
    )
    for text in pages:
        page = writer.add_blank_page(400, 400)
        page[NameObject("/Resources")] = DictionaryObject(
            {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})}
        )
        stream = DecodedStreamObject()
        stream.set_data(f"BT /F1 8 Tf 10 350 Td ({text}) Tj ET".encode())
        page[NameObject("/Contents")] = writer._add_object(stream)
    writer.set_page_label(0, len(pages) - 1, style="/D", start=10)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as f:
        writer.write(f)


def session(label: str, topic: str) -> Session:
    return Session(
        label=label,
        number=None,
        date=None,
        topic=topic,
        subtopics=[],
        required_readings=[],
        optional_readings=[],
    )


def course(root: Path) -> None:
    """Course 1: session s1 has an excerpt of the book (PDF pp. 1-2), s2 a Markdown handout."""
    text_pdf(root / "1/reading/book.pdf", BOOK_PAGES)
    put(root, "1/excerpts/s1/book - Ch. 1.pdf")
    put(
        root,
        "1/reading/handout.md",
        b"# Vector spaces\nA vector space is a set closed under addition.\n\n"
        b"Every vector space has a basis.",
    )
    put_transcript(
        root,
        Transcript(
            language="en",
            learning_materials=[],
            sessions=[session("Week 1", "Linear systems"), session("Week 2", "Vector spaces")],
            notes=None,
            source_path="1/syllabus/s.pdf",
            source_sha256="x",
            model="test/model",
            created_at="2026-10-01T00:00:00+00:00",
        ),
    )
    put_plan(
        root,
        "1",
        Plan(
            primary="1/syllabus/s.pdf",
            sessions=[
                PlanSession(
                    id="s1", label="Week 1", number=None, files=["1/excerpts/s1/book - Ch. 1.pdf"]
                ),
                PlanSession(id="s2", label="Week 2", number=None, files=["1/reading/handout.md"]),
            ],
            books=[
                BookMatch(material=0, raw="Hefferon. Linear Algebra.", file="1/reading/book.pdf")
            ],
            proposals=[
                Proposal(
                    id="p1",
                    session_id="s1",
                    reading="[1] Ch. 1",
                    book="1/reading/book.pdf",
                    label="Ch. 1",
                    pdf_start=1,
                    pdf_end=2,
                    printed="pp. 10–11",
                    method="bookmarks",
                    status="approved",
                    excerpt="1/excerpts/s1/book - Ch. 1.pdf",
                )
            ],
        ),
    )
