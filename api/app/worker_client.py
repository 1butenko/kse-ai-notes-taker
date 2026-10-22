from collections.abc import AsyncIterator
from typing import Annotated

import httpx2
from fastapi import Depends, HTTPException, status
from pydantic import BaseModel

from app.config import Settings, get_settings
from app.notes_revisions import EditResult
from app.worker_contract import (
    MapRequest,
    MapResponse,
    NotesRequest,
    NotesResponse,
    RestoreRequest,
    ReviseRequest,
    TranscribeRequest,
    TranscribeResponse,
)


class WorkerClient:
    """The API's only way to reach a model: every AI call is routed to the worker service."""

    def __init__(self, base_url: str, http: httpx2.AsyncClient) -> None:
        self.base_url = base_url.rstrip("/")
        self.http = http

    async def transcribe(self, request: TranscribeRequest) -> TranscribeResponse:
        return await self.call("/transcribe", request, TranscribeResponse)

    async def map_materials(self, request: MapRequest) -> MapResponse:
        return await self.call("/map", request, MapResponse)

    async def generate_notes(self, request: NotesRequest) -> NotesResponse:
        return await self.call("/notes", request, NotesResponse)

    async def revise_notes(self, request: ReviseRequest) -> EditResult:
        return await self.call("/notes/revise", request, EditResult)

    async def restore_notes(self, request: RestoreRequest) -> EditResult:
        return await self.call("/notes/restore", request, EditResult)

    async def call[T: BaseModel](self, path: str, request: BaseModel, response: type[T]) -> T:
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
) -> AsyncIterator[WorkerClient]:
    # A run can take minutes: bound connecting, not the wait for the model.
    async with httpx2.AsyncClient(timeout=httpx2.Timeout(None, connect=5)) as http:
        yield WorkerClient(settings.worker_url, http)
