from collections.abc import AsyncIterator
from typing import Annotated, Any

import httpx2
from fastapi import Depends
from pydantic import BaseModel

from app.config import Settings, get_settings


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


class Course(BaseModel):
    id: int
    shortname: str
    fullname: str
    categoryid: int = 0
    summary: str = ""
    visible: int = 1
    startdate: int = 0
    enddate: int = 0


class ModuleContent(BaseModel):
    type: str
    filename: str
    fileurl: str = ""
    filesize: int = 0
    mimetype: str = ""
    timemodified: int = 0


class Module(BaseModel):
    id: int
    name: str
    modname: str
    url: str = ""
    visible: int = 1
    contents: list[ModuleContent] = []


class Section(BaseModel):
    id: int
    section: int
    name: str
    summary: str = ""
    visible: int = 1
    modules: list[Module] = []


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

    async def get_courses(self, token: str, ids: list[int] | None = None) -> list[Course]:
        params = {f"options[ids][{i}]": course_id for i, course_id in enumerate(ids or [])}
        payload = await self.call(token, "core_course_get_courses", **params)
        return [Course.model_validate(item) for item in payload]

    async def get_courses_by_field(
        self, token: str, field: str = "", value: str | int = ""
    ) -> list[Course]:
        payload = await self.call(
            token, "core_course_get_courses_by_field", field=field, value=value
        )
        return [Course.model_validate(item) for item in payload["courses"]]

    async def get_course_contents(self, token: str, courseid: int) -> list[Section]:
        payload = await self.call(token, "core_course_get_contents", courseid=courseid)
        return [Section.model_validate(item) for item in payload]


async def get_moodle_client(
    settings: Annotated[Settings, Depends(get_settings)],
) -> AsyncIterator[MoodleClient]:
    async with httpx2.AsyncClient(timeout=15) as http:
        yield MoodleClient(settings.moodle_url, http)
