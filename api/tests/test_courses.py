import httpx2
from fastapi.testclient import TestClient

from app.main import app
from app.routers.courses import REQUIRED_FUNCTIONS

SITE_INFO = {
    "userid": 42,
    "username": "lecturer",
    "fullname": "Test Lecturer",
    "sitename": "KSE Teaching",
    "siteurl": "https://teaching.kse.org.ua",
    "release": "4.5",
    "downloadfiles": 1,
    "functions": [{"name": name, "version": "2024100700"} for name in REQUIRED_FUNCTIONS],
}


def test_connect_returns_site_info(mock_moodle) -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen["url"] = str(request.url)
        seen["body"] = request.content.decode()
        return httpx2.Response(200, json=SITE_INFO)

    response = mock_moodle(handler).post("/courses/connect", json={"token": "abc123"})

    assert response.status_code == 200
    assert response.json() == {
        "status": "connected",
        "fullname": "Test Lecturer",
        "username": "lecturer",
        "sitename": "KSE Teaching",
        "release": "4.5",
        "downloadfiles": True,
        "missing_functions": [],
    }
    assert seen["url"] == "https://moodle.test/webservice/rest/server.php"
    assert "wstoken=abc123" in seen["body"]
    assert "wsfunction=core_webservice_get_site_info" in seen["body"]
    assert "moodlewsrestformat=json" in seen["body"]


def test_connect_reports_missing_functions(mock_moodle) -> None:
    info = {**SITE_INFO, "downloadfiles": 0, "functions": []}
    client = mock_moodle(lambda _: httpx2.Response(200, json=info))

    body = client.post("/courses/connect", json={"token": "abc123"}).json()

    assert body["downloadfiles"] is False
    assert body["missing_functions"] == REQUIRED_FUNCTIONS


def test_connect_rejects_invalid_token(mock_moodle) -> None:
    error = {"exception": "moodle_exception", "errorcode": "invalidtoken", "message": "x"}
    client = mock_moodle(lambda _: httpx2.Response(200, json=error))

    response = client.post("/courses/connect", json={"token": "bad"})

    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid Moodle token"}


def test_connect_reports_other_moodle_errors(mock_moodle) -> None:
    error = {"exception": "moodle_exception", "errorcode": "accessexception", "message": "x"}
    client = mock_moodle(lambda _: httpx2.Response(200, json=error))

    response = client.post("/courses/connect", json={"token": "abc123"})

    assert response.status_code == 502
    assert response.json() == {"detail": "Moodle error: accessexception"}


def test_connect_reports_unreachable_moodle(mock_moodle) -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("boom", request=request)

    response = mock_moodle(handler).post("/courses/connect", json={"token": "abc123"})

    assert response.status_code == 502
    assert response.json() == {"detail": "Moodle is unreachable"}


def test_connect_rejects_empty_token() -> None:
    response = TestClient(app).post("/courses/connect", json={"token": ""})
    assert response.status_code == 422


def test_connect_allows_web_origin() -> None:
    response = TestClient(app).options(
        "/courses/connect",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"


COURSE = {
    "id": 4510,
    "shortname": "MICRO",
    "fullname": "Microeconomics",
    "categoryid": 3,
    "summary": "",
    "visible": 1,
    "startdate": 1756684800,
    "enddate": 1767225600,
}


def test_get_course_by_id(mock_moodle) -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen["body"] = request.content.decode()
        return httpx2.Response(200, json={"courses": [COURSE], "warnings": []})

    response = mock_moodle(handler).get("/courses/4510")

    assert response.status_code == 200
    assert response.json() == COURSE
    assert "wstoken=test-token" in seen["body"]
    assert "wsfunction=core_course_get_courses_by_field" in seen["body"]
    assert "field=id" in seen["body"]
    assert "value=4510" in seen["body"]


def test_get_course_not_found(mock_moodle) -> None:
    client = mock_moodle(lambda _: httpx2.Response(200, json={"courses": [], "warnings": []}))

    response = client.get("/courses/4510")

    assert response.status_code == 404
    assert response.json() == {"detail": "Course not found"}


def test_get_course_rejects_invalid_token(mock_moodle) -> None:
    error = {"exception": "moodle_exception", "errorcode": "invalidtoken", "message": "x"}
    client = mock_moodle(lambda _: httpx2.Response(200, json=error))

    response = client.get("/courses/4510")

    assert response.status_code == 401


CONTENTS = [
    {
        "id": 1,
        "section": 0,
        "name": "Syllabus",
        "summary": "",
        "visible": 1,
        "modules": [
            {
                "id": 10,
                "name": "Syllabus v.1.0",
                "modname": "resource",
                "url": "https://moodle.test/mod/resource/view.php?id=10",
                "visible": 1,
                "contents": [
                    {
                        "type": "file",
                        "filename": "syllabus.pdf",
                        "fileurl": "https://moodle.test/webservice/pluginfile.php/1/syllabus.pdf",
                        "filesize": 245000,
                        "mimetype": "application/pdf",
                        "timemodified": 1756684800,
                    }
                ],
            },
            {
                "id": 11,
                "name": "Assignment 01",
                "modname": "assign",
                "url": "https://moodle.test/mod/assign/view.php?id=11",
                "visible": 1,
                "contents": [],
            },
        ],
    }
]


def test_get_course_contents(mock_moodle, capsys) -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen["body"] = request.content.decode()
        return httpx2.Response(200, json=CONTENTS)

    response = mock_moodle(handler).get("/courses/4510/contents")

    assert response.status_code == 200
    assert response.json() == CONTENTS
    assert "wstoken=test-token" in seen["body"]
    assert "wsfunction=core_course_get_contents" in seen["body"]
    assert "courseid=4510" in seen["body"]

    printed = capsys.readouterr().out
    assert "Section 0: Syllabus (2 modules)" in printed
    assert "[resource] Syllabus v.1.0" in printed
    assert "file: syllabus.pdf, 245000 bytes" in printed


def test_get_course_contents_moodle_error(mock_moodle) -> None:
    error = {"exception": "moodle_exception", "errorcode": "invalidrecord", "message": "x"}
    client = mock_moodle(lambda _: httpx2.Response(200, json=error))

    response = client.get("/courses/4510/contents")

    assert response.status_code == 502
    assert response.json() == {"detail": "Moodle error: invalidrecord"}
