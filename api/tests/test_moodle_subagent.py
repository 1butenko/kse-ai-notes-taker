import io
import json

from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, HumanMessage

from app.note_taker.agent import build_note_taker
from app.note_taker.moodle.client import MoodleClient, MoodleError, Section
from app.note_taker.moodle.store import MaterialRecord
from app.note_taker.moodle.tools import _IterReader, make_moodle_tools
from app.note_taker.subagents.moodle import build_moodle_subagent

COURSE_ID = "00000000-0000-0000-0000-000000000001"
MOODLE_COURSE_ID = 42
PDF_URL = "https://moodle.test/pluginfile.php/1/slides.pdf"
PAGE_URL = "https://moodle.test/pluginfile.php/2/index.html"

CONTENTS = [
    {
        "id": 1,
        "section": 1,
        "name": "Week 1",
        "summary": "<p>Intro</p>",
        "modules": [
            {
                "id": 10,
                "name": "Slides",
                "modname": "resource",
                "contents": [
                    {
                        "type": "file",
                        "filename": "slides.pdf",
                        "fileurl": PDF_URL,
                        "filesize": 100,
                        "mimetype": "application/pdf",
                        "timemodified": 5,
                    }
                ],
            },
            {
                "id": 11,
                "name": "Reading",
                "modname": "page",
                "contents": [{"type": "file", "filename": "index.html", "fileurl": PAGE_URL}],
            },
            {"id": 12, "name": "Quiz 1", "modname": "quiz"},
            {"id": 13, "name": "Hidden", "modname": "resource", "visible": 0},
            {
                "id": 14,
                "name": "Welcome",
                "modname": "label",
                "description": "<p>Read <b>everything</b></p>",
            },
        ],
    }
]


class ScriptedModel(GenericFakeChatModel):
    def bind_tools(self, tools, **kwargs) -> "ScriptedModel":
        return self


class FakeMoodle(MoodleClient):
    def __init__(self) -> None:
        super().__init__("https://moodle.test", "tok")
        self.downloads: list[str] = []

    def get_course_contents(self, moodle_course_id: int) -> list[Section]:
        assert moodle_course_id == MOODLE_COURSE_ID
        return [Section.model_validate(s) for s in CONTENTS]

    def iter_download(self, fileurl: str):
        self.downloads.append(fileurl)
        yield b"%PDF-"
        yield b"1.7"

    def get_page_html(self, fileurl: str) -> str:
        return "<h1>Eigen</h1><script>x()</script><p>values</p>"


class MemoryStore:
    def __init__(self) -> None:
        self.records: list[MaterialRecord] = []

    def exists(self, course_id, source_url, timemodified) -> bool:
        return any(
            r.source_url == source_url and r.moodle_timemodified == timemodified
            for r in self.records
        )

    def add(self, record: MaterialRecord) -> None:
        self.records.append(record)

    def save_topics(self, course_id, topics) -> None:
        self.topics = topics


class FakeBackend:
    def __init__(self) -> None:
        self.files: dict[str, bytes] = {}

    def upload_files(self, files) -> None:
        self.files.update(dict(files))


def make_tools():
    uploads: dict[str, bytes] = {}

    def upload(key, fileobj, content_type) -> None:
        uploads[key] = fileobj.read()

    client, store, backend = FakeMoodle(), MemoryStore(), FakeBackend()
    made = make_moodle_tools(client, backend, store, COURSE_ID, MOODLE_COURSE_ID, upload=upload)
    return {t.name: t for t in made}, client, store, backend, uploads


def test_list_course_contents_outlines_and_saves_the_catalog() -> None:
    tools, _, store, backend, _ = make_tools()
    outline = tools["list_course_contents"].invoke({})
    assert "[10] resource: Slides | slides.pdf (application/pdf" in outline
    assert "[12] quiz: Quiz 1" in outline
    assert "Hidden" not in outline
    catalog = json.loads(backend.files["/moodle/catalog.json"])
    assert {i["module_id"] for i in catalog["items"]} == {10, 11, 12, 14}
    assert [(t.section, t.name) for t in store.topics] == [(1, "Week 1")]


def test_preview_module_gives_text_without_downloading_files() -> None:
    tools, client, _, _, _ = make_tools()
    page = tools["preview_module"].invoke({"module_id": 11})
    assert "Eigen" in page and "values" in page and "x()" not in page
    assert "Read everything" in tools["preview_module"].invoke({"module_id": 14})
    assert "slides.pdf" in tools["preview_module"].invoke({"module_id": 10})
    assert "No module 99" in tools["preview_module"].invoke({"module_id": 99})
    assert client.downloads == []


def test_fetch_materials_stores_chosen_files_and_writes_the_manifest() -> None:
    tools, _, store, backend, uploads = make_tools()
    result = tools["fetch_materials"].invoke(
        {
            "items": [
                {"module_id": 10, "reason": "lecture slides"},
                {"module_id": 12, "reason": "quiz"},
                {"module_id": 99, "reason": "invented"},
            ]
        }
    )
    assert result.startswith("fetched 1, skipped 1, failed 1")
    [key] = uploads
    assert key.startswith(f"courses/{COURSE_ID}/materials/") and key.endswith("/slides.pdf")
    assert uploads[key] == b"%PDF-1.7"
    [record] = store.records
    assert (record.size, record.reason, record.moodle_module_id) == (8, "lecture slides", 10)
    assert (record.section, record.section_name) == (1, "Week 1")
    manifest = json.loads(backend.files["/materials/manifest.json"])
    assert manifest["fetched"][0]["s3_key"] == key
    assert "quiz modules hold no study material" in manifest["skipped"][0]["why"]
    assert manifest["failed"][0]["error"] == "not in the course catalog"


def test_second_fetch_skips_unchanged_files() -> None:
    tools, client, store, _, uploads = make_tools()
    items = {"items": [{"module_id": 10, "reason": "slides"}]}
    tools["fetch_materials"].invoke(items)
    result = tools["fetch_materials"].invoke(items)
    assert len(uploads) == 1 and len(store.records) == 1
    assert client.downloads == [PDF_URL]
    assert "skipped 1" in result


def test_failed_download_is_reported_and_does_not_stop_the_rest() -> None:
    tools, client, store, _, uploads = make_tools()
    original = client.iter_download

    def flaky(fileurl):
        if fileurl == PDF_URL:
            raise MoodleError("invalidtoken", "Invalid token")
        yield from original(fileurl)

    client.iter_download = flaky
    result = tools["fetch_materials"].invoke(
        {"items": [{"module_id": 10, "reason": "a"}, {"module_id": 11, "reason": "b"}]}
    )
    assert "failed 1" in result and "Invalid token" in result
    # The page module is not downloaded as raw HTML: it is saved as a Markdown reading.
    assert store.records == []
    assert not uploads


def test_page_modules_are_saved_as_web_pages_not_files() -> None:
    tools, _, store, _, uploads = make_tools()
    tools["fetch_materials"].invoke({"items": [{"module_id": 11, "reason": "notes"}]})
    assert store.records == [] and not uploads


def test_unknown_file_name_fails_without_downloading() -> None:
    tools, client, store, _, _ = make_tools()
    result = tools["fetch_materials"].invoke(
        {"items": [{"module_id": 10, "filename": "other.pdf", "reason": "x"}]}
    )
    assert "failed 1" in result and not store.records and client.downloads == []


def test_subagent_spec_and_approval_gate() -> None:
    args = (FakeMoodle(), MemoryStore(), FakeBackend(), COURSE_ID, MOODLE_COURSE_ID)
    spec = build_moodle_subagent(*args)
    assert spec["name"] == "moodle" and "interrupt_on" not in spec
    assert {t.name for t in spec["tools"]} == {
        "list_course_contents",
        "preview_module",
        "fetch_materials",
    }
    gated = build_moodle_subagent(*args, approval=True)
    assert gated["interrupt_on"] == {"fetch_materials": True}


def test_main_agent_delegates_to_moodle_end_to_end() -> None:
    uploads: dict[str, bytes] = {}
    store = MemoryStore()

    def call(name, args, id_):
        return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": id_}])

    # The subagent has no model of its own, so it shares the main one and one script covers both.
    model = ScriptedModel(
        messages=iter(
            [
                call(
                    "task",
                    {"subagent_type": "moodle", "description": "Gather the materials"},
                    "t1",
                ),
                call("list_course_contents", {}, "s1"),
                call("fetch_materials", {"items": [{"module_id": 10, "reason": "slides"}]}, "s2"),
                AIMessage(content="Fetched slides.pdf."),
                AIMessage(content="Report: fetched slides."),
            ]
        )
    )
    agent = build_note_taker(
        COURSE_ID,
        MOODLE_COURSE_ID,
        model=model,
        moodle_client=FakeMoodle(),
        materials=store,
        upload=lambda key, fileobj, content_type: uploads.__setitem__(key, fileobj.read()),
    )
    result = agent.invoke({"messages": [HumanMessage(content="Make notes")]})
    assert result["messages"][-1].text == "Report: fetched slides."
    assert len(uploads) == 1 and [r.name for r in store.records] == ["slides.pdf"]
    assert {"/moodle/catalog.json", "/materials/manifest.json"} <= set(result["files"])


def test_iter_reader_streams_chunks_and_counts_bytes() -> None:
    reader = _IterReader(iter([b"ab", b"cde"]))
    assert io.BufferedReader(reader).read() == b"abcde" and reader.size == 5


def test_url_modules_point_to_their_target_not_the_moodle_page() -> None:
    from app.note_taker.moodle.catalog import normalize_contents, outline

    section = Section.model_validate(
        {
            "id": 2,
            "section": 1,
            "name": "Lectures",
            "modules": [
                {
                    "id": 20,
                    "name": "01 - Forecasting",
                    "modname": "url",
                    "url": "https://moodle.test/mod/url/view.php?id=20",
                    "contents": [
                        {
                            "type": "url",
                            "filename": "01 - Forecasting",
                            "fileurl": "https://slides.test/forecasting/",
                        }
                    ],
                }
            ],
        }
    )
    catalog = normalize_contents([section])
    assert catalog.find(20).url == "https://slides.test/forecasting/"
    assert "[20] url: 01 - Forecasting -> https://slides.test/forecasting/" in outline(catalog)


def test_preview_link_reads_pages_as_markdown_and_names_videos() -> None:
    import httpx

    from app.note_taker.moodle.tools import preview_link

    html = r"<html><body><main><h2>ARIMA</h2><p>Model \(y_t\)</p></main></body></html>"
    http = httpx.Client(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, text=html, headers={"content-type": "text/html"})
        )
    )
    assert preview_link("https://slides.test/arima", 500, http) == "## ARIMA\n\nModel $y_t$"
    assert "video" in preview_link("https://www.youtube.com/watch?v=x", 500)


def test_a_file_name_copied_with_the_module_name_still_fetches_the_file() -> None:
    tools, client, _, _, _ = make_tools()
    result = tools["fetch_materials"].invoke(
        {"items": [{"module_id": 10, "filename": "Slides | slides.pdf", "reason": "x"}]}
    )
    assert "fetched 1" in result and "failed 0" in result
    assert client.downloads == [PDF_URL]
