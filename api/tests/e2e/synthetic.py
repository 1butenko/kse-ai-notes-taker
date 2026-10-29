"""Synthetic course for the notes E2E stack: seed files and the scripted LLM answers.

Everything is derived from tests/fixtures/notes so the browser stack, backend tests and
visual QA share one control content. Nothing here reads production uploads or keys.
"""

import json
import re
import shutil
from pathlib import Path

from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from app.notes import CoursePlan, NotesDocument, NotesRun
from app.plan import Plan, PlanSession
from app.syllabus import Session, Transcript

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "notes"
COURSE = "local"
LEGACY_RUN = "20261001-000000-0001"
SESSIONS = [
    ("Тиждень 1", "Системи лінійних рівнянь", "linear-systems.md"),
    ("Тиждень 2", "Власні значення та власні вектори", "eigenvalues.md"),
]


def control_document() -> NotesDocument:
    return NotesDocument.model_validate_json((FIXTURES / "control.json").read_text())


def course_plan() -> CoursePlan:
    return CoursePlan.model_validate_json((FIXTURES / "course-plan.json").read_text())


def text_pdf(path: Path, lines: list[str]) -> None:
    """A real one-page PDF with extractable text (ASCII: the base-14 font has no Cyrillic)."""
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
    page = writer.add_blank_page(420, 300)
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})}
    )
    text = " ".join(f"({line}) Tj 0 -16 Td" for line in lines)
    stream = DecodedStreamObject()
    stream.set_data(f"BT /F1 11 Tf 24 260 Td {text} ET".encode())
    page[NameObject("/Contents")] = writer._add_object(stream)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as f:
        writer.write(f)


def seed(uploads: Path) -> None:
    """Course `local`: syllabus, transcript, plan, two readings and one legacy run."""
    course = uploads / COURSE
    if course.exists():
        raise FileExistsError(f"Refusing to seed over an existing course: {course}")
    syllabus = f"{COURSE}/syllabus/s.pdf"
    text_pdf(
        uploads / syllabus,
        ["Synthetic E2E syllabus", "Week 1: Linear systems", "Week 2: Eigenvalues"],
    )
    transcript = Transcript(
        language="uk",
        learning_materials=[],
        sessions=[
            Session(
                label=label,
                number=number,
                date=None,
                topic=topic,
                subtopics=[],
                required_readings=[],
                optional_readings=[],
            )
            for number, (label, topic, _) in enumerate(SESSIONS, 1)
        ],
        notes=None,
        source_path=syllabus,
        source_sha256="synthetic-e2e",
        model="e2e/transcriber",
        created_at="2026-10-23T00:00:00+00:00",
    )
    (uploads / f"{syllabus}.transcript.json").write_text(transcript.model_dump_json())
    for _, _, name in SESSIONS:
        target = course / "reading" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(FIXTURES / "reading" / name, target)
    plan = Plan(
        primary=syllabus,
        sessions=[
            PlanSession(
                id=f"s{number}", label=label, number=number, files=[f"{COURSE}/reading/{name}"]
            )
            for number, (label, _, name) in enumerate(SESSIONS, 1)
        ],
    )
    (course / "plan.json").write_text(plan.model_dump_json())

    # A finished run written before schema metadata existed: fields are genuinely absent.
    legacy = course / "notes" / LEGACY_RUN
    legacy.mkdir(parents=True)
    shutil.copyfile(FIXTURES / "legacy-notes.json", legacy / "notes.json")
    stamp = "2026-10-01T00:00:00+00:00"
    run = NotesRun(
        id=LEGACY_RUN,
        course=COURSE,
        status="done",
        stage="done",
        created_at=stamp,
        updated_at=stamp,
        models={"generator": "e2e/legacy"},
    )
    (legacy / "run.json").write_text(run.model_dump_json())


# Scripted LLM answers, chosen by response schema and by the topic named in the prompt.


def topic_of(prompt: str) -> str | None:
    """The control topic a prompt is about, found by its title: a lecture run numbers its
    topics from T1, so the second lecture's topic is T1 there and control topic T2 here."""
    for _, topic in course_plan().topics():
        if re.search(rf"Topic T\d+: {re.escape(topic.title)}", prompt):
            return topic.id
    for topic in ("T1", "T2"):
        if f"Topic {topic}:" in prompt:
            return topic
    return None


def lecture_plan(prompt: str) -> dict:
    """The plan of one lecture (its transcript is S0 alone): the control topic it teaches."""
    plan = course_plan()
    found = next(
        ((section, t) for section, t in plan.topics() if f": {t.title}" in prompt.split("S0:")[1]),
        None,
    )
    if found is None:
        raise UnknownRequest("No control topic for this lecture")
    section, topic = found
    single = topic.model_copy(update={"id": "T1", "sessions": [0], "sources": [0]})
    single.prerequisites = []
    return plan.model_copy(
        update={
            "title": topic.title,
            "sections": [section.model_copy(update={"title": topic.title, "topics": [single]})],
        }
    ).model_dump()


def draft(topic: str) -> dict:
    """The control blocks of a topic, minus the figure: a generated run has no registered
    assets, so images arrive later through the asset/revision interfaces."""
    note = next(t for s in control_document().sections for t in s.topics if t.topic_id == topic)
    return {
        "blocks": [
            {
                "kind": block.kind,
                "title": block.title,
                "content": block.content,
                "citations": [0] if block.citations else [],
            }
            for block in note.blocks
            if "![" not in block.content
        ]
    }


UNRESOLVED_ISSUE = {
    "block": 4,
    "kind": "unsupported_claim",
    "severity": "major",
    "detail": "Синтетичні джерела не містять спектральної теореми.",
    "fix": "Додати джерело з доведенням або прибрати твердження.",
}


def verification(topic: str) -> dict:
    """T1 passes; T2 keeps one major issue through every revision and escalation."""
    failing = topic == "T2"
    return {
        "passed": not failing,
        "issues": [UNRESOLVED_ISSUE] if failing else [],
        "escalate": False,
        "escalation_reason": None,
    }


# What the prompt of a suggestion request names: the selected block IDs and the instruction.
# The prompt is a JSON-encoded message list, so a newline may appear escaped.
SELECTED = re.compile(r'Selected block IDs: ([^"\\\n]*)')
INSTRUCTION = re.compile(r'Instruction:(?:\\n|\n)([^"\\]*)')


def suggestion(topic: str, prompt: str) -> dict:
    """Changes for the first selected block: a simpler text, or a worked example after it.

    The text is plain, so applying it never breaks a label or a reference."""
    selected = SELECTED.search(prompt)
    asked = INSTRUCTION.search(prompt)
    ids = [i.strip() for i in (selected.group(1) if selected else "").split(",") if i.strip()]
    note = next(t for s in control_document().sections for t in s.topics if t.topic_id == topic)
    block = next((b for b in note.blocks if ids and b.id == ids[0]), None)
    if block is None or asked is None:
        raise UnknownRequest(f"No block selected for the suggestion of {topic}")
    cited = [0] if block.citations else []
    if "example" in asked.group(1).lower():
        return {
            "replacements": [],
            "insertions": [
                {
                    "after_block_id": block.id,
                    "kind": "example",
                    "title": "Додатковий приклад",
                    "content": (
                        "Розглянемо систему $x + y = 2$, $x - y = 0$. Її розв'язок: $x = y = 1$."
                    ),
                    "citations": [0],
                }
            ],
        }
    return {
        "replacements": [
            {
                "block_id": block.id,
                "kind": block.kind,
                "title": block.title,
                "content": "Простіше кажучи: оборотні перетворення рядків не змінюють розв'язків.",
                "citations": cited,
            }
        ],
        "insertions": [],
    }


SCHEMAS = (
    "course_plan",
    "coverage_review",
    "evidence_selection",
    "topic_draft",
    "topic_verification",
    "consistency_edits",
    "topic_suggestion",
    "page_transcript",
)


class UnknownRequest(ValueError):
    pass


def answer(body: dict) -> tuple[dict, dict]:
    """The JSON answer for one chat completion request and a log record describing it."""
    name = body["response_format"]["json_schema"]["name"]
    prompt = "\n".join(
        m["content"]
        if isinstance(m["content"], str)
        else json.dumps(m["content"], ensure_ascii=False)
        for m in body["messages"]
    )
    topic = topic_of(prompt)
    record = {
        "schema": name,
        "model": body.get("model"),
        "topic": topic,
        "revision": "Previous draft:" in prompt,
        "reasoning": body.get("reasoning"),
    }
    if name == "course_plan" and "one lecture of the course" in prompt:
        result = lecture_plan(prompt)
    elif name == "course_plan":
        result = json.loads((FIXTURES / "course-plan.json").read_text())
    elif name == "coverage_review":
        result = {"approved": True, "issues": []}
    elif name == "evidence_selection":
        result = {
            "selected": [
                {"candidate": 0, "role": "definition", "relevance": 5, "reason": "Own reading"},
                {"candidate": 1, "role": "complementary", "relevance": 3, "reason": "Context"},
            ],
            "gaps": [],
        }
    elif name == "page_transcript":
        result = {"markdown": "Transcribed page."}
    elif name == "consistency_edits":
        result = {"edits": []}
    elif name == "topic_suggestion" and topic:
        result = suggestion(topic, prompt)
    elif name in ("topic_draft", "topic_verification") and topic:
        result = draft(topic) if name == "topic_draft" else verification(topic)
    else:
        raise UnknownRequest(f"No scripted answer for schema={name!r} topic={topic!r}")
    return result, record


if __name__ == "__main__":
    import sys

    if len(sys.argv) != 3 or sys.argv[1] != "seed":
        raise SystemExit("usage: python -m tests.e2e.synthetic seed <uploads-dir>")
    seed(Path(sys.argv[2]))
