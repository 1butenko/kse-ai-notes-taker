import httpx2
from fastapi.testclient import TestClient

from app.links import get_web_client
from app.main import app


def test_upload_files_saves_to_course_category(tmp_uploads) -> None:
    response = TestClient(app).post(
        "/uploads",
        data={"category": "syllabus", "course_id": "4510"},
        files=[("files", ("syllabus.pdf", b"%PDF-1.4 test", "application/pdf"))],
    )

    assert response.status_code == 200
    assert response.json() == [{"path": "4510/syllabus/syllabus.pdf", "size": 13}]
    assert (tmp_uploads / "4510/syllabus/syllabus.pdf").read_bytes() == b"%PDF-1.4 test"


def test_upload_files_without_course_goes_to_local(tmp_uploads) -> None:
    response = TestClient(app).post(
        "/uploads",
        data={"category": "reading"},
        files=[
            ("files", ("a.pdf", b"a", "application/pdf")),
            ("files", ("b.pdf", b"bb", "application/pdf")),
        ],
    )

    assert response.status_code == 200
    assert [f["path"] for f in response.json()] == ["local/reading/a.pdf", "local/reading/b.pdf"]


def test_upload_files_strips_path_from_name(tmp_uploads) -> None:
    response = TestClient(app).post(
        "/uploads",
        data={"category": "reading"},
        files=[("files", ("../../etc/passwd", b"x", "text/plain"))],
    )

    assert response.status_code == 200
    assert response.json()[0]["path"] == "local/reading/..-..-etc-passwd"
    assert not (tmp_uploads.parent / "etc").exists()


def test_upload_files_rejects_unknown_category(tmp_uploads) -> None:
    response = TestClient(app).post(
        "/uploads",
        data={"category": "videos"},
        files=[("files", ("a.pdf", b"a", "application/pdf"))],
    )
    assert response.status_code == 422


def test_upload_moodle_files_downloads_with_token(mock_moodle, tmp_uploads) -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen["url"] = str(request.url)
        return httpx2.Response(
            200, content=b"%PDF moodle", headers={"content-type": "application/pdf"}
        )

    response = mock_moodle(handler).post(
        "/uploads/moodle",
        json={
            "category": "syllabus",
            "course_id": 4510,
            "files": [
                {
                    "fileurl": "https://moodle.test/webservice/pluginfile.php/1/s.pdf?forcedownload=1",
                    "filename": "Syllabus v.1.0.pdf",
                }
            ],
        },
    )

    assert response.status_code == 200
    assert response.json() == [{"path": "4510/syllabus/Syllabus v.1.0.pdf", "size": 11}]
    assert (tmp_uploads / "4510/syllabus/Syllabus v.1.0.pdf").read_bytes() == b"%PDF moodle"
    assert "forcedownload=1" in seen["url"]
    assert "token=test-token" in seen["url"]


def test_upload_moodle_files_rejects_foreign_url(mock_moodle, tmp_uploads) -> None:
    client = mock_moodle(lambda _: httpx2.Response(200, content=b"x"))

    response = client.post(
        "/uploads/moodle",
        json={
            "category": "syllabus",
            "files": [{"fileurl": "https://evil.test/steal", "filename": "x.pdf"}],
        },
    )

    assert response.status_code == 400
    assert not any(tmp_uploads.iterdir())


def test_upload_moodle_files_reports_moodle_error(mock_moodle, tmp_uploads) -> None:
    error = {"error": "x", "errorcode": "invalidtoken", "exception": "moodle_exception"}
    client = mock_moodle(lambda _: httpx2.Response(200, json=error))

    response = client.post(
        "/uploads/moodle",
        json={
            "category": "syllabus",
            "files": [
                {
                    "fileurl": "https://moodle.test/webservice/pluginfile.php/1/s.pdf",
                    "filename": "s.pdf",
                }
            ],
        },
    )

    assert response.status_code == 401


COURSE_LINKS = [
    {
        "id": 1,
        "section": 0,
        "name": "Study Materials",
        "modules": [
            {
                "id": 11,
                "name": "01 - Introduction",
                "modname": "url",
                "contents": [
                    {"type": "url", "filename": "x", "fileurl": "https://slides.test/01/"}
                ],
            },
            {
                "id": 12,
                "name": "Paper",
                "modname": "url",
                "contents": [{"type": "url", "filename": "x", "fileurl": "https://papers.test/p"}],
            },
            {
                "id": 13,
                "name": "Lecture video",
                "modname": "url",
                "contents": [
                    {"type": "url", "filename": "x", "fileurl": "https://www.youtube.com/watch?v=1"}
                ],
            },
        ],
    }
]

SLIDES = """<html><head><title>T</title><script>var x = 1;</script></head><body>
<nav>Table of contents</nav>
<section><h2>Forecasting</h2><p>A model  \\(y = f(X)\\) of
the future.</p><ul><li>one</li><li>two</li></ul></section>
<section><h2></h2></section></body></html>"""


def links_client(mock_moodle, pages: dict[str, httpx2.Response]):
    async def web():
        async with httpx2.AsyncClient(
            transport=httpx2.MockTransport(lambda request: pages[str(request.url)])
        ) as client:
            yield client

    client = mock_moodle(lambda _: httpx2.Response(200, json=COURSE_LINKS))
    app.dependency_overrides[get_web_client] = web
    return client


def test_upload_moodle_links_saves_pages_as_text_and_pdfs(mock_moodle, tmp_uploads) -> None:
    client = links_client(
        mock_moodle,
        {
            "https://slides.test/01/": httpx2.Response(
                200, text=SLIDES, headers={"content-type": "text/html; charset=utf-8"}
            ),
            "https://papers.test/p": httpx2.Response(
                200, content=b"%PDF-1.7 paper", headers={"content-type": "application/pdf"}
            ),
        },
    )

    response = client.post("/uploads/moodle/links", json={"course_id": 4510, "modules": [11, 12]})

    assert response.status_code == 200, response.text
    assert [f["path"] for f in response.json()] == [
        "4510/reading/01 - Introduction.md",
        "4510/reading/Paper.pdf",
    ]
    assert (tmp_uploads / "4510/reading/01 - Introduction.md").read_text() == (
        "# 01 - Introduction\n\nSource: https://slides.test/01/\n\n"
        "## Forecasting\n\nA model $y = f(X)$ of the future.\n\n- one\n\n- two\n"
    )
    assert (tmp_uploads / "4510/reading/Paper.pdf").read_bytes() == b"%PDF-1.7 paper"


def test_upload_moodle_links_only_fetches_web_pages_of_the_course(mock_moodle, tmp_uploads) -> None:
    client = links_client(mock_moodle, {})

    video = client.post("/uploads/moodle/links", json={"course_id": 4510, "modules": [13]})
    foreign = client.post("/uploads/moodle/links", json={"course_id": 4510, "modules": [99]})

    assert video.status_code == 422
    assert foreign.status_code == 404
    assert not (tmp_uploads / "4510/reading").exists() or not any(
        (tmp_uploads / "4510/reading").iterdir()
    )
