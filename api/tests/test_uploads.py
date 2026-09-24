import httpx2
from fastapi.testclient import TestClient

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
