from collections.abc import AsyncIterator
from typing import Any

import httpx2
from pydantic import BaseModel

from app.config import settings


class MoodleError(Exception):
    def __init__(self, errorcode: str, message: str) -> None:
        super().__init__(message)
        self.errorcode = errorcode
        self.message = message


class SiteFunction(BaseModel):
    name: str
    version: str


class SiteInfo(BaseModel):
    userid: int
    username: str
    fullname: str
    sitename: str
    siteurl: str
    release: str
    downloadfiles: int = 0
    functions: list[SiteFunction] = []

    def has_function(self, name: str) -> bool:
        return any(f.name == name for f in self.functions)


class MoodleClient:
    def __init__(self, base_url: str, http: httpx2.AsyncClient) -> None:
        self.endpoint = f"{base_url.rstrip('/')}/webservice/rest/server.php"
        self.http = http

    async def call(self, token: str, wsfunction: str, **params: Any) -> Any:
        response = await self.http.post(
            self.endpoint,
            data={
                "wstoken": token,
                "wsfunction": wsfunction,
                "moodlewsrestformat": "json",
                **params,
            },
        )
        response.raise_for_status()
        payload = response.json()
        if isinstance(payload, dict) and "exception" in payload:
            raise MoodleError(payload.get("errorcode", "unknown"), payload.get("message", ""))
        return payload

    async def get_site_info(self, token: str) -> SiteInfo:
        return SiteInfo.model_validate(await self.call(token, "core_webservice_get_site_info"))


async def get_moodle_client() -> AsyncIterator[MoodleClient]:
    async with httpx2.AsyncClient(timeout=15) as http:
        yield MoodleClient(settings.moodle_url, http)
