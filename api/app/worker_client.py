from collections.abc import AsyncIterator
from typing import Annotated
from uuid import UUID

import httpx2
from fastapi import Depends, HTTPException, status
from pydantic import BaseModel

from app.auth import CurrentPrincipal
from app.config import Settings, get_settings
from app.worker_contract import (
    BooksRequest,
    BooksResponse,
    LectureNotesCancel,
    LectureNotesCancelResponse,
    LectureNotesRequest,
    LectureNotesResponse,
    MapRequest,
    MapResponse,
    NoteTakerRequest,
    NoteTakerResponse,
    Traced,
    TranscribeRequest,
    TranscribeResponse,
)


class WorkerClient:
    """The API's only way to reach a model: every AI call is routed to the worker service.
    Requests that call a model carry `user_id`, who asked, for Langfuse."""

    def __init__(self, base_url: str, http: httpx2.AsyncClient, user_id: str | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.http = http
        self.user_id = user_id

    async def transcribe(self, request: TranscribeRequest) -> TranscribeResponse:
        return await self.call("/transcribe", request, TranscribeResponse)

    async def map_materials(self, request: MapRequest) -> MapResponse:
        return await self.call("/map", request, MapResponse)

    async def transcribe_books(self, request: BooksRequest) -> BooksResponse:
        return await self.call("/books/transcribe", request, BooksResponse)

    async def run_note_taker(self, request: NoteTakerRequest) -> NoteTakerResponse:
        return await self.call("/note-taker/runs", request, NoteTakerResponse)

    async def run_lecture_notes(self, request: LectureNotesRequest) -> LectureNotesResponse:
        return await self.call("/lecture-notes/runs", request, LectureNotesResponse)

    async def cancel_lecture_notes(self, run_id: UUID) -> LectureNotesCancelResponse:
        return await self.call(
            "/lecture-notes/cancel", LectureNotesCancel(run_id=run_id), LectureNotesCancelResponse
        )

    async def call[T: BaseModel](self, path: str, request: BaseModel, response: type[T]) -> T:
        if isinstance(request, Traced) and request.user_id is None:
            request = request.model_copy(update={"user_id": self.user_id})
        try:
            reply = await self.http.post(
                f"{self.base_url}{path}",
                content=request.model_dump_json(),
                headers={"Content-Type": "application/json"},
            )
        except httpx2.TimeoutException as error:
            print(f"Worker timed out ({path}): {error!r}")
            raise HTTPException(status.HTTP_504_GATEWAY_TIMEOUT, "The worker timed out") from error
        except httpx2.HTTPError as error:
            print(f"Worker unreachable ({path}): {error!r}")
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, "The worker is unavailable") from error

        if reply.is_error:
            try:
                detail = reply.json()["detail"]
            except (ValueError, KeyError, TypeError):
                detail = "The worker request failed"
            raise HTTPException(reply.status_code, detail)
        return response.model_validate_json(reply.content)


async def get_worker_client(
    settings: Annotated[Settings, Depends(get_settings)],
    principal: CurrentPrincipal,
) -> AsyncIterator[WorkerClient]:
    # A run can take minutes: bound connecting, not the wait for the model.
    async with httpx2.AsyncClient(timeout=httpx2.Timeout(None, connect=5)) as http:
        yield WorkerClient(settings.worker_url, http, principal.id)
