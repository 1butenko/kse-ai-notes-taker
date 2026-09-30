import io
import json
import zipfile
from pathlib import Path

import httpx2
from fastapi.testclient import TestClient

from app.main import app
from app.syllabus import SyllabusExtraction
from app.worker.llm import strict_schema
from app.worker.main import app as worker_app
from app.worker.openrouter import get_openrouter_client
from app.worker_client import WorkerClient, get_worker_client

EXTRACTION = {
    "language": "en",
    "learning_materials": [
        {
            "raw": "Mankiw, N. G. Principles of Economics. 2020.",
            "title": "Principles of Economics",
            "authors": ["N. G. Mankiw"],
            "year": "2020",
            "url": None,
            "pages": None,
        }
    ],
    "sessions": [
        {
            "label": "Week 1",
            "number": 1,
            "date": None,
            "topic": "Demand and supply",
            "subtopics": ["Markets"],
            "required_readings": [
                {
                    "raw": "Mankiw, ch. 3",
                    "title": None,
                    "authors": ["Mankiw"],
                    "year": None,
                    "url": None,
                    "pages": "ch. 3",
                    "material_ref": 0,
                }
            ],
            "optional_readings": [
                {
                    "raw": "Some article",
                    "title": "Some article",
                    "authors": [],
                    "year": None,
                    "url": None,
                    "pages": None,
                    "material_ref": 7,
                }
            ],
        }
    ],
    "notes": None,
}


def completion(content: str) -> httpx2.Response:
    return httpx2.Response(200, json={"choices": [{"message": {"content": content}}]})


def make_docx(text: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as docx:
        docx.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/'
            'content-types"><Default Extension="rels" ContentType="application/vnd.openxml'
            'formats-package.relationships+xml"/><Default Extension="xml" ContentType="applic'
            'ation/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.'
            'openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>',
        )
        docx.writestr(
            "_rels/.rels",
            '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/pack'
            'age/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlforma'
            'ts.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xm'
            'l"/></Relationships>',
        )
        body = f"<w:p><w:r><w:t>{text}</w:t></w:r></w:p>" if text else ""
        docx.writestr(
            "word/document.xml",
            '<?xml version="1.0"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordpr'
            f'ocessingml/2006/main"><w:body>{body}</w:body></w:document>',
        )
    return buffer.getvalue()


def put(root: Path, path: str, data: bytes) -> None:
    file = root / path
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_bytes(data)


def test_transcribe_pdf_sends_native_file_and_saves_transcript(mock_openrouter, tmp_uploads):
    put(tmp_uploads, "4510/syllabus/s.pdf", b"%PDF-1.4 test")
    seen: dict = {}

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers["authorization"]
        seen["body"] = json.loads(request.content)
        return completion(json.dumps(EXTRACTION))

    response = mock_openrouter(handler).post(
        "/syllabus/transcribe", json={"path": "4510/syllabus/s.pdf"}
    )

    assert response.status_code == 200
    data = response.json()
    assert data["source_path"] == "4510/syllabus/s.pdf"
    assert data["model"] == "test/model"
    assert data["sessions"][0]["required_readings"][0]["material_ref"] == 0
    assert data["sessions"][0]["optional_readings"][0]["material_ref"] is None

    body = seen["body"]
    assert seen["url"] == "https://openrouter.test/api/v1/chat/completions"
    assert seen["auth"] == "Bearer or-key"
    assert body["plugins"] == [{"id": "file-parser", "pdf": {"engine": "native"}}]
    assert body["provider"] == {"require_parameters": True}
    assert body["response_format"]["json_schema"]["strict"] is True
    file_part = body["messages"][1]["content"][1]
    assert file_part["file"]["file_data"].startswith("data:application/pdf;base64,")

    saved = json.loads((tmp_uploads / "4510/syllabus/s.pdf.transcript.json").read_text())
    assert saved == data


def test_transcribe_docx_sends_html_without_plugins(mock_openrouter, tmp_uploads):
    put(tmp_uploads, "local/syllabus/s.docx", make_docx("Week 1: Demand"))
    seen: dict = {}

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen["body"] = json.loads(request.content)
        return completion(json.dumps(EXTRACTION))

    response = mock_openrouter(handler).post(
        "/syllabus/transcribe", json={"path": "local/syllabus/s.docx"}
    )

    assert response.status_code == 200
    assert "plugins" not in seen["body"]
    assert "<p>Week 1: Demand</p>" in seen["body"]["messages"][1]["content"][0]["text"]


def test_transcribe_returns_cached_unless_changed_or_forced(mock_openrouter, tmp_uploads):
    put(tmp_uploads, "1/syllabus/s.pdf", b"%PDF v1")
    calls = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        calls.append(1)
        return completion(json.dumps(EXTRACTION))

    client = mock_openrouter(handler)
    body = {"path": "1/syllabus/s.pdf"}

    assert client.post("/syllabus/transcribe", json=body).status_code == 200
    assert client.post("/syllabus/transcribe", json=body).status_code == 200
    assert len(calls) == 1

    assert client.post("/syllabus/transcribe?force=true", json=body).status_code == 200
    assert len(calls) == 2

    put(tmp_uploads, "1/syllabus/s.pdf", b"%PDF v2")
    assert client.post("/syllabus/transcribe", json=body).status_code == 200
    assert len(calls) == 3


def test_get_transcript(mock_openrouter, tmp_uploads):
    put(tmp_uploads, "1/syllabus/s.pdf", b"%PDF")
    client = mock_openrouter(lambda _: completion(json.dumps(EXTRACTION)))

    params = {"path": "1/syllabus/s.pdf"}
    assert client.get("/syllabus/transcript", params=params).status_code == 404
    client.post("/syllabus/transcribe", json=params)
    response = client.get("/syllabus/transcript", params=params)
    assert response.status_code == 200
    assert response.json()["sessions"][0]["label"] == "Week 1"


def test_transcribe_rejects_bad_paths(mock_openrouter, tmp_uploads):
    put(tmp_uploads, "1/reading/book.pdf", b"%PDF")
    put(tmp_uploads, "1/syllabus/s.txt", b"text")
    put(tmp_uploads, "1/syllabus/big.pdf", b"0" * (20 * 1024 * 1024 + 1))
    client = mock_openrouter(lambda _: completion(json.dumps(EXTRACTION)))

    def status_of(path: str) -> int:
        return client.post("/syllabus/transcribe", json={"path": path}).status_code

    assert status_of("../../etc/passwd") == 400
    assert status_of("1/reading/book.pdf") == 400
    assert status_of("1/syllabus/missing.pdf") == 404
    assert status_of("1/syllabus/s.txt") == 415
    assert status_of("1/syllabus/big.pdf") == 413


def test_transcribe_empty_docx_is_422(mock_openrouter, tmp_uploads):
    put(tmp_uploads, "1/syllabus/empty.docx", make_docx(""))
    put(tmp_uploads, "1/syllabus/broken.docx", b"not a zip")
    client = mock_openrouter(lambda _: completion(json.dumps(EXTRACTION)))

    for name in ("empty.docx", "broken.docx"):
        response = client.post("/syllabus/transcribe", json={"path": f"1/syllabus/{name}"})
        assert response.status_code == 422


def test_transcribe_invalid_model_output_is_502(mock_openrouter, tmp_uploads):
    put(tmp_uploads, "1/syllabus/s.pdf", b"%PDF")
    client = mock_openrouter(lambda _: completion('{"sessions": "nope"}'))

    response = client.post("/syllabus/transcribe", json={"path": "1/syllabus/s.pdf"})

    assert response.status_code == 502
    assert not (tmp_uploads / "1/syllabus/s.pdf.transcript.json").exists()


def test_transcribe_openrouter_error_is_502(mock_openrouter, tmp_uploads):
    put(tmp_uploads, "1/syllabus/s.pdf", b"%PDF")
    client = mock_openrouter(
        lambda _: httpx2.Response(402, json={"error": {"message": "Insufficient credits"}})
    )

    response = client.post("/syllabus/transcribe", json={"path": "1/syllabus/s.pdf"})
    assert response.status_code == 502


def test_transcribe_timeout_is_504(mock_openrouter, tmp_uploads):
    put(tmp_uploads, "1/syllabus/s.pdf", b"%PDF")

    def handler(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ReadTimeout("slow", request=request)

    response = mock_openrouter(handler).post(
        "/syllabus/transcribe", json={"path": "1/syllabus/s.pdf"}
    )
    assert response.status_code == 504


def test_transcribe_without_key_is_503(tmp_uploads):
    put(tmp_uploads, "1/syllabus/s.pdf", b"%PDF")

    async def no_client():
        yield None

    worker_app.dependency_overrides[get_openrouter_client] = no_client
    response = TestClient(app).post("/syllabus/transcribe", json={"path": "1/syllabus/s.pdf"})
    assert response.status_code == 503


def test_strict_schema_has_no_refs_and_requires_every_field():
    schema = strict_schema(SyllabusExtraction)
    assert "$ref" not in json.dumps(schema)
    session = schema["properties"]["sessions"]["items"]
    assert set(session["required"]) == set(session["properties"])
    assert session["additionalProperties"] is False


def test_transcribe_with_worker_down_is_502(tmp_uploads):
    put(tmp_uploads, "1/syllabus/s.pdf", b"%PDF")

    def refuse(_: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("refused")

    async def down():
        async with httpx2.AsyncClient(transport=httpx2.MockTransport(refuse)) as http:
            yield WorkerClient("http://worker.test", http)

    app.dependency_overrides[get_worker_client] = down
    response = TestClient(app).post("/syllabus/transcribe", json={"path": "1/syllabus/s.pdf"})
    assert response.status_code == 502
    assert response.json()["detail"] == "The worker is unavailable"
