"""Local OpenRouter stand-in for the notes E2E stack; replaces only the LLM.

Run from api/:  NOTES_E2E_MOCK_LOG=<file.jsonl> python -m uvicorn tests.e2e.mock_openrouter:app
Every request is appended to the JSONL log; unknown schemas fail loudly with HTTP 500.
"""

import json
import os
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from tests.e2e.synthetic import UnknownRequest, answer

app = FastAPI(title="notes-e2e-mock-openrouter")


def log(record: dict) -> None:
    target = os.environ.get("NOTES_E2E_MOCK_LOG")
    if target:
        with Path(target).open("a") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/v1/chat/completions")
async def chat_completions(request: Request) -> JSONResponse:
    body = await request.json()
    try:
        result, record = answer(body)
    except (UnknownRequest, KeyError, TypeError) as error:
        log({"error": str(error), "model": body.get("model") if isinstance(body, dict) else None})
        return JSONResponse({"error": {"message": f"notes-e2e mock: {error}"}}, status_code=500)
    log(record)
    return JSONResponse(
        {
            "model": body["model"],
            "choices": [{"message": {"content": json.dumps(result, ensure_ascii=False)}}],
        }
    )
