"""The AI Note Taker filling the app's course: materials into the course, the syllabus read into
lectures, readings attached, and every step reported for the course page."""

import json

import httpx
import pytest

from app.note_taker.moodle.client import Section
from app.note_taker.moodle.tools import make_moodle_tools
from app.note_taker.progress import Progress
from app.note_taker.project import Project, ProjectError
from app.note_taker.sync import MainAgentProgress
from tests.test_moodle_subagent import (
    CONTENTS,
    COURSE_ID,
    MOODLE_COURSE_ID,
    PDF_URL,
    FakeBackend,
    FakeMoodle,
    MemoryStore,
)

SYLLABUS_URL = "https://moodle.test/pluginfile.php/3/syllabus.pdf"

WITH_SYLLABUS_AND_LINKS = [
    {
        **CONTENTS[0],
        "modules": [
            *CONTENTS[0]["modules"],
            {
                "id": 15,
                "name": "Syllabus",
                "modname": "resource",
                "contents": [
                    {
                        "type": "file",
                        "filename": "syllabus.pdf",
                        "fileurl": SYLLABUS_URL,
                        "mimetype": "application/pdf",
                    }
                ],
            },
            {
                "id": 16,
                "name": "Time series graphics",
                "modname": "url",
                "contents": [{"type": "url", "fileurl": "https://otexts.com/fpp3/graphics.html"}],
            },
        ],
    }
]

PLAN = {
    "primary": "42/syllabus/syllabus.pdf",
    "sessions": [
        {
            "id": "s1",
            "session": {"label": "Week 1", "topic": "Graphics"},
            "files": [],
            "proposals": [],
        },
        {
            "id": "s2",
            "session": {"label": "Week 2", "topic": "Decomposition"},
            "files": [{"path": "42/reading/slides.pdf"}],
            "proposals": [],
        },
    ],
    "unassigned": [
        {"path": "42/reading/Time series graphics.md"},
        {"path": "42/reading/slides.pdf"},
    ],
    "books": [{"file": "42/reading/book.pdf"}, {"file": None}],
}


class CourseMoodle(FakeMoodle):
    def get_course_contents(self, moodle_course_id: int) -> list[Section]:
        return [Section.model_validate(s) for s in WITH_SYLLABUS_AND_LINKS]


class FakeProject:
    def __init__(self, syllabus: str | None = "42/syllabus/syllabus.pdf") -> None:
        self.syllabus = syllabus
        self.calls: list[tuple] = []

    def save_files(self, category, files):
        self.calls.append(("save_files", category, files))
        return [{"path": f"42/{category}/{name}", "size": 1} for _, name in files]

    def save_link(self, module_id):
        self.calls.append(("save_link", module_id))
        return [{"path": "42/reading/Time series graphics.md", "size": 1}]

    def syllabus_path(self):
        return self.syllabus

    def read_syllabus(self, path):
        self.calls.append(("read_syllabus", path))
        return {"sessions": [{}, {}], "learning_materials": [{}, {}]}

    def map_readings(self):
        self.calls.append(("map_readings",))
        return PLAN

    def plan(self):
        return PLAN

    def attach(self, session_id, path):
        if session_id == "missing":
            raise ProjectError("Session not found")
        self.calls.append(("attach", session_id, path))
        return PLAN


def course_tools(project: FakeProject | None = None):
    progress = Progress()
    backend = FakeBackend()
    made = make_moodle_tools(
        CourseMoodle(),
        backend,
        MemoryStore(),
        COURSE_ID,
        MOODLE_COURSE_ID,
        upload=lambda key, fileobj, content_type: fileobj.read(),
        project=project or FakeProject(),
        progress=progress,
    )
    return {t.name: t for t in made}, progress, backend


def test_without_a_project_the_subagent_has_only_the_moodle_tools() -> None:
    made = make_moodle_tools(
        FakeMoodle(), FakeBackend(), MemoryStore(), COURSE_ID, MOODLE_COURSE_ID
    )
    assert [t.name for t in made] == ["list_course_contents", "preview_module", "fetch_materials"]


def test_fetch_adds_the_syllabus_readings_and_link_pages_to_the_course() -> None:
    project = FakeProject()
    tools, progress, backend = course_tools(project)

    result = tools["fetch_materials"].invoke(
        {
            "items": [
                {"module_id": 15, "category": "syllabus", "reason": "the syllabus"},
                {"module_id": 10, "reason": "lecture slides"},
                {"module_id": 16, "reason": "book chapter"},
            ]
        }
    )

    assert "added to the course 3" in result
    assert project.calls == [
        ("save_files", "syllabus", [(SYLLABUS_URL, "syllabus.pdf")]),
        ("save_files", "reading", [(PDF_URL, "slides.pdf")]),
        ("save_link", 16),
    ]
    manifest = json.loads(backend.files["/materials/manifest.json"])
    assert len(manifest["saved"]) == 3
    assert [(a.text, a.status) for a in progress.actions] == [
        ("Downloading 3 materials from Moodle", "done"),
        ("Adding 1 syllabus file to the course", "done"),
        ("Adding 1 reading file to the course", "done"),
        ("Saving the web page “Time series graphics”", "done"),
    ]
    assert progress.actions[0].detail == "2 new, 0 skipped, 0 failed"


def test_a_failed_link_is_reported_and_the_rest_is_kept() -> None:
    project = FakeProject()

    def no_videos(module_id):
        raise ProjectError("Time series graphics: only web pages can be imported")

    project.save_link = no_videos
    tools, progress, backend = course_tools(project)

    tools["fetch_materials"].invoke({"items": [{"module_id": 16, "reason": "video"}]})

    manifest = json.loads(backend.files["/materials/manifest.json"])
    assert manifest["failed"][0]["error"].endswith("only web pages can be imported")
    assert progress.actions[-1].status == "failed"


def test_prepare_lectures_reads_the_syllabus_and_maps_the_books() -> None:
    project = FakeProject()
    tools, progress, backend = course_tools(project)

    result = tools["prepare_lectures"].invoke({})

    assert project.calls == [("read_syllabus", "42/syllabus/syllabus.pdf"), ("map_readings",)]
    assert "- [s1] Week 1: Graphics (0 readings)" in result
    assert "- [s2] Week 2: Decomposition (1 reading)" in result
    # A reading attached to a lecture is no longer listed as unattached.
    assert "- 42/reading/Time series graphics.md" in result
    assert "- 42/reading/slides.pdf" not in result
    lectures = json.loads(backend.files["/course/lectures.json"])
    assert lectures["unattached_readings"] == ["42/reading/Time series graphics.md"]
    assert [(a.text, a.detail) for a in progress.actions] == [
        ("Finding the syllabus in the course", "syllabus.pdf"),
        ("Reading the syllabus into lectures", "2 lectures, 2 books"),
        ("Matching the cited books to the readings", "1 of 2 books found"),
    ]


def test_prepare_lectures_without_a_syllabus_asks_for_one() -> None:
    tools, progress, _ = course_tools(FakeProject(syllabus=None))
    assert "has no PDF or DOCX syllabus" in tools["prepare_lectures"].invoke({})
    assert progress.actions[-1].status == "failed"


def test_attach_readings_reports_each_failure() -> None:
    project = FakeProject()
    tools, progress, _ = course_tools(project)

    result = tools["attach_readings"].invoke(
        {
            "attachments": [
                {"session_id": "s1", "path": "42/reading/Time series graphics.md"},
                {"session_id": "missing", "path": "42/reading/slides.pdf"},
            ]
        }
    )

    assert ("attach", "s1", "42/reading/Time series graphics.md") in project.calls
    assert result.startswith("- 42/reading/slides.pdf -> missing: Session not found")
    assert progress.actions[-1].detail == "1 attached, 1 failed"


def test_progress_saves_every_change_and_names_the_current_step() -> None:
    saved = []
    progress = Progress(save=lambda todos, actions, step: saved.append((todos, actions, step)))

    progress.set_todos(
        [
            {"content": "Gather the course materials from Moodle", "status": "in_progress"},
            {"content": "Report back", "status": "pending"},
        ]
    )
    assert saved[-1][2] == "Gather the course materials from Moodle"
    with progress.action("Reading the course outline in Moodle") as action:
        assert saved[-1][2] == "Reading the course outline in Moodle"
        action.detail = "12 activities"
    assert saved[-1][1] == [
        {
            "text": "Reading the course outline in Moodle",
            "status": "done",
            "detail": "12 activities",
        }
    ]
    with pytest.raises(RuntimeError), progress.action("Downloading"):
        raise RuntimeError("Moodle is down")
    assert saved[-1][1][-1] == {
        "text": "Downloading",
        "status": "failed",
        "detail": "Moodle is down",
    }


def test_a_failed_save_never_stops_the_run() -> None:
    def broken(*_):
        raise RuntimeError("database down")

    progress = Progress(save=broken)
    with progress.action("Reading the course outline in Moodle"):
        pass
    assert progress.actions[0].status == "done"


def test_main_agent_todos_and_hand_offs_are_recorded() -> None:
    progress = Progress()
    callback = MainAgentProgress(progress)

    callback.on_tool_start(
        {"name": "write_todos"},
        "",
        inputs={"todos": [{"content": "Read the syllabus into lectures", "status": "pending"}]},
    )
    callback.on_tool_start({"name": "task"}, "", inputs={"subagent_type": "moodle"})
    callback.on_tool_start({"name": "read_file"}, "", inputs={"file_path": "/x"})

    assert progress.todo_list == [
        {"content": "Read the syllabus into lectures", "status": "pending"}
    ]
    assert [a.text for a in progress.actions] == ["Handing the work to the moodle agent"]


def test_project_maps_and_approves_found_and_estimated_excerpts() -> None:
    seen = []
    estimated = {
        "id": "p2",
        "status": "proposed",
        "method": "toc",
        "pdf_start": 3,
        "pdf_end": 9,
    }
    missing = {"id": "p3", "status": "proposed", "method": "toc", "pdf_start": None, "pdf_end": 1}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.path, request.content.decode() or None))
        if request.url.path.endswith("/approve-all"):
            return httpx.Response(200, json={"sessions": [{"proposals": [estimated, missing]}]})
        return httpx.Response(200, json={"sessions": []})

    project = Project(
        "42", httpx.Client(transport=httpx.MockTransport(handler), base_url="http://api")
    )
    project.map_readings()

    assert seen == [
        ("POST", "/plans/42/map", None),
        ("POST", "/plans/42/proposals/approve-all", None),
        ("POST", "/plans/42/proposals/p2/approve", '{"pdf_start":3,"pdf_end":9}'),
    ]


def test_project_errors_carry_the_api_detail() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(409, json={"detail": "Transcribe a syllabus first"})

    project = Project(
        "42", httpx.Client(transport=httpx.MockTransport(handler), base_url="http://api")
    )
    with pytest.raises(ProjectError, match="Transcribe a syllabus first"):
        project.map_readings()
