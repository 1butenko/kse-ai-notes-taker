import json
from pathlib import Path

import httpx2
from fastapi.testclient import TestClient
from pypdf import PdfReader, PdfWriter

from app.books import entry_end, printed_range, read_index, to_pdf
from app.main import app
from app.plan import Plan
from app.storage import sha256
from app.syllabus import Reading, Session, SessionReading, Transcript
from tests.test_plans import put_plan, put_transcript

# A 40-page book: pages 1-2 are front matter (i, ii), printed page n is PDF page n + 2.
OUTLINE = [
    ("1 Linear Systems", 0, 3),
    ("1.1 Gauss's Method", 1, 3),
    ("1.2 Echelon Form", 1, 8),
    ("2 Vector Spaces", 0, 15),
    ("2.1 Definition", 1, 15),
    ("2.2 Basis", 1, 20),
    ("3 Maps", 0, 30),
]


def make_book(path: Path, *, outline=OUTLINE, labels: bool = True, pages: int = 40) -> None:
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=200, height=200)
    parent = None
    for title, level, page in outline:
        item = writer.add_outline_item(title, page - 1, parent=parent if level else None)
        if level == 0:
            parent = item
    if labels:
        writer.set_page_label(0, 1, style="/r", start=1)
        writer.set_page_label(2, pages - 1, style="/D", start=1)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as f:
        writer.write(f)


def reading(raw: str, pages: str | None, ref: int | None) -> SessionReading:
    return SessionReading(
        raw=raw, title=None, authors=[], year=None, url=None, pages=pages, material_ref=ref
    )


def session(label: str, *readings: SessionReading) -> Session:
    return Session(
        label=label,
        number=None,
        date=None,
        topic=label,
        subtopics=[],
        required_readings=list(readings),
        optional_readings=[],
    )


def course(root: Path, *sessions: Session) -> None:
    material = Reading(
        raw="[1] Hefferon. Linear Algebra.",
        title="Linear Algebra",
        authors=["Hefferon"],
        year=None,
        url=None,
        pages=None,
    )
    put_transcript(
        root,
        Transcript(
            language="en",
            learning_materials=[material],
            sessions=list(sessions),
            notes=None,
            source_path="1/syllabus/s.pdf",
            source_sha256="x",
            model="test/model",
            created_at="2026-09-30T00:00:00+00:00",
        ),
    )
    put_plan(root, "1", Plan(primary="1/syllabus/s.pdf"))


def answers(**by_schema) -> tuple[callable, dict[str, int]]:
    """An OpenRouter stand-in answering by schema name; counts the calls."""
    calls: dict[str, int] = {}

    def handler(request: httpx2.Request) -> httpx2.Response:
        name = json.loads(request.content)["response_format"]["json_schema"]["name"]
        calls[name] = calls.get(name, 0) + 1
        content = json.dumps(by_schema[name])
        return httpx2.Response(200, json={"choices": [{"message": {"content": content}}]})

    return handler, calls


def span(start=None, end=None, printed_start=None, printed_end=None, label="x") -> dict:
    return {
        "start_entry": start,
        "end_entry": end,
        "printed_start": printed_start,
        "printed_end": printed_end,
        "label": label,
    }


MATCH = {"materials": [{"item": 0, "file": 0}], "citations": [{"item": 0, "file": None}]}


# Book index


def test_read_index_uses_bookmarks_and_page_labels(tmp_path: Path) -> None:
    make_book(tmp_path / "b.pdf")
    index = read_index(tmp_path / "b.pdf", "sha")

    assert index.method == "bookmarks"
    assert [(e.title, e.level, e.pdf_page) for e in index.entries] == OUTLINE
    assert index.page_labels[:4] == ["i", "ii", "1", "2"]
    assert to_pdf(index, 6) == 8
    assert printed_range(index, 3, 14) == "pp. 1–12"


def test_entry_end_stops_before_next_chapter_but_keeps_shared_section_page(tmp_path) -> None:
    make_book(tmp_path / "b.pdf")
    index = read_index(tmp_path / "b.pdf", "sha")

    assert entry_end(index, 0) == 14  # chapter 1 ends before chapter 2
    assert entry_end(index, 1) == 8  # 1.1 runs into the page where 1.2 starts
    assert entry_end(index, 2) == 14  # 1.2 is the chapter's last section
    assert entry_end(index, 6) == 40  # last chapter runs to the end


# Mapping


def test_map_approve_detach_reject_cycle(mock_openrouter, tmp_uploads) -> None:
    make_book(tmp_uploads / "1/reading/hefferon.pdf")
    course(
        tmp_uploads,
        session("Lecture 1", reading("[1] Chapter 1.1-1.2", "Chapter 1.1-1.2", 0)),
        session(
            "Lecture 2",
            reading("[1] pp. 13-17", "pp. 13-17", 0),
            reading("Some article, p. 5", "p. 5", None),
        ),
    )
    ranges = {
        "readings": [
            {"reading": 0, "ranges": [span(1, 2, label="Ch. 1.1-1.2")], "note": None},
            {"reading": 1, "ranges": [span(printed_start=13, printed_end=17)], "note": None},
        ]
    }
    handler, calls = answers(book_match=MATCH, reading_ranges=ranges)
    client = mock_openrouter(handler)

    plan = client.post("/plans/1/map").json()

    assert plan["books"] == [
        {
            "material": 0,
            "raw": "[1] Hefferon. Linear Algebra.",
            "file": "1/reading/hefferon.pdf",
            "confirmed": False,
        }
    ]
    first, second = (s["proposals"] for s in plan["sessions"])
    assert [(p["pdf_start"], p["pdf_end"], p["method"], p["printed"]) for p in first] == [
        (3, 14, "bookmarks", "pp. 1–12")
    ]
    assert [(p["pdf_start"], p["pdf_end"], p["method"]) for p in second] == [(15, 19, "pages")]
    assert calls == {"book_match": 1, "reading_ranges": 1}
    assert (tmp_uploads / "1/index/hefferon.pdf.json").is_file()

    plan = client.post("/plans/1/proposals/approve-all").json()
    files = plan["sessions"][0]["files"]
    assert len(files) == 1 and files[0]["excerpt"]["printed"] == "pp. 1–12"
    excerpt = tmp_uploads / files[0]["path"]
    assert len(PdfReader(excerpt).pages) == 12
    assert client.get("/files", params={"path": files[0]["path"]}).status_code == 200

    session_id = plan["sessions"][0]["id"]
    plan = client.delete(
        f"/plans/1/sessions/{session_id}/files", params={"path": files[0]["path"]}
    ).json()
    assert not excerpt.exists()
    proposal = plan["sessions"][0]["proposals"][0]
    assert proposal["status"] == "proposed" and proposal["excerpt"] is None

    client.post(f"/plans/1/proposals/{proposal['id']}/reject")
    plan = client.post("/plans/1/map").json()
    assert [p["status"] for p in plan["sessions"][0]["proposals"]] == ["rejected"]
    assert [p["status"] for p in plan["sessions"][1]["proposals"]] == ["approved"]

    client.post(f"/plans/1/proposals/{proposal['id']}/reopen")
    plan = client.post(
        f"/plans/1/proposals/{proposal['id']}/approve", json={"pdf_start": 5, "pdf_end": 6}
    ).json()
    approved = plan["sessions"][0]["proposals"][0]
    assert (approved["status"], approved["method"], approved["printed"]) == (
        "approved",
        "manual",
        "pp. 3–4",
    )
    assert len(PdfReader(tmp_uploads / approved["excerpt"]).pages) == 2


def test_approve_rejects_bad_pages_and_ai_estimates_need_one_by_one(
    mock_openrouter, tmp_uploads
) -> None:
    make_book(tmp_uploads / "1/reading/b.pdf", outline=[], labels=False, pages=20)
    course(tmp_uploads, session("Lecture 1", reading("[1] Ch. 1", "Ch. 1", 0)))
    toc = {
        "entries": [
            {"title": "1 Intro", "level": 0, "printed_page": 1},
            {"title": "2 More", "level": 0, "printed_page": 9},
        ],
        "samples": [{"pdf_page": 8, "printed_page": 6}, {"pdf_page": 12, "printed_page": 10}],
    }
    ranges = {"readings": [{"reading": 0, "ranges": [span(0, 0)], "note": None}]}
    handler, calls = answers(book_match=MATCH, book_toc=toc, reading_ranges=ranges)
    client = mock_openrouter(handler)

    plan = client.post("/plans/1/map").json()
    proposal = plan["sessions"][0]["proposals"][0]
    assert (proposal["pdf_start"], proposal["pdf_end"], proposal["method"]) == (3, 10, "toc")
    assert proposal["printed"] == "pp. 1–8"
    assert calls["book_toc"] == 1

    plan = client.post("/plans/1/proposals/approve-all").json()
    assert plan["sessions"][0]["proposals"][0]["status"] == "proposed"

    url = f"/plans/1/proposals/{proposal['id']}/approve"
    assert client.post(url, json={"pdf_start": 9, "pdf_end": 3}).status_code == 400
    assert client.post(url, json={"pdf_start": 1, "pdf_end": 99}).status_code == 400
    assert client.post(url).status_code == 200
    assert client.post(url).status_code == 409


def test_printed_pages_without_labels_ask_for_the_offset(mock_openrouter, tmp_uploads) -> None:
    make_book(tmp_uploads / "1/reading/b.pdf", labels=False)
    course(tmp_uploads, session("Lecture 1", reading("[1] p. 5-6", "p. 5-6", 0)))
    ranges = {
        "readings": [{"reading": 0, "ranges": [span(printed_start=5, printed_end=6)], "note": None}]
    }
    offset = {
        "samples": [{"pdf_page": 16, "printed_page": 14}, {"pdf_page": 24, "printed_page": 22}]
    }
    handler, calls = answers(book_match=MATCH, reading_ranges=ranges, page_offset=offset)

    plan = mock_openrouter(handler).post("/plans/1/map").json()

    proposal = plan["sessions"][0]["proposals"][0]
    assert (proposal["pdf_start"], proposal["pdf_end"], proposal["printed"]) == (7, 8, "pp. 5–6")
    assert calls["page_offset"] == 1


def test_unlocatable_reading_gets_empty_proposal_with_note(mock_openrouter, tmp_uploads) -> None:
    make_book(tmp_uploads / "1/reading/b.pdf")
    course(tmp_uploads, session("Lecture 1", reading("[1] Appendix Z", "Appendix Z", 0)))
    ranges = {"readings": [{"reading": 0, "ranges": [span(99, 99)], "note": "No appendix Z"}]}
    handler, _ = answers(book_match=MATCH, reading_ranges=ranges)

    plan = mock_openrouter(handler).post("/plans/1/map").json()

    proposal = plan["sessions"][0]["proposals"][0]
    assert proposal["pdf_start"] is None and proposal["note"] == "No appendix Z"


def test_confirmed_book_choice_survives_remapping(mock_openrouter, tmp_uploads) -> None:
    make_book(tmp_uploads / "1/reading/b.pdf")
    course(tmp_uploads, session("Lecture 1", reading("[1] Ch. 1", "Ch. 1", 0)))
    ranges = {"readings": [{"reading": 0, "ranges": [span(0, 0)], "note": None}]}
    handler, calls = answers(book_match=MATCH, reading_ranges=ranges)
    client = mock_openrouter(handler)
    client.post("/plans/1/map")

    plan = client.put("/plans/1/books/0", json={"file": None}).json()
    assert plan["books"][0] == {**plan["books"][0], "file": None, "confirmed": True}
    assert plan["sessions"][0]["proposals"] == []

    plan = client.post("/plans/1/map").json()
    assert plan["books"][0]["file"] is None
    assert plan["sessions"][0]["proposals"] == []

    assert client.put("/plans/1/books/5", json={"file": None}).status_code == 404
    (tmp_uploads / "1/reading/notes.docx").write_bytes(b"x")
    assert client.put("/plans/1/books/0", json={"file": "1/reading/notes.docx"}).status_code == 400


def test_map_needs_a_transcript_and_a_key(tmp_uploads) -> None:
    assert TestClient(app).post("/plans/1/map").status_code == 409


def test_index_is_cached_by_file_hash(mock_openrouter, tmp_uploads) -> None:
    book = tmp_uploads / "1/reading/b.pdf"
    make_book(book)
    course(tmp_uploads, session("Lecture 1", reading("[1] Ch. 1", "Ch. 1", 0)))
    ranges = {"readings": [{"reading": 0, "ranges": [span(0, 0)], "note": None}]}
    handler, _ = answers(book_match=MATCH, reading_ranges=ranges)
    mock_openrouter(handler).post("/plans/1/map")

    cached = json.loads((tmp_uploads / "1/index/b.pdf.json").read_text())
    assert cached["source_sha256"] == sha256(book)


# Files


def test_files_endpoint_serves_only_uploads(tmp_uploads) -> None:
    make_book(tmp_uploads / "1/reading/b.pdf", labels=False, pages=2)
    put_plan(tmp_uploads, "1", Plan())
    client = TestClient(app)

    response = client.get("/files", params={"path": "1/reading/b.pdf"})
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["content-disposition"].startswith("inline")

    assert client.get("/files", params={"path": "../../etc/passwd"}).status_code == 400
    assert client.get("/files", params={"path": "1/plan.json"}).status_code == 400
    assert client.get("/files", params={"path": "1/reading/missing.pdf"}).status_code == 404
