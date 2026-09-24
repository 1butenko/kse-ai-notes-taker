from collections.abc import Iterator
from contextlib import contextmanager
from typing import Annotated

import httpx2
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.config import Settings, get_settings
from app.moodle import Course, MoodleClient, MoodleError, Section, get_moodle_client

router = APIRouter(prefix="/courses", tags=["courses"])

REQUIRED_FUNCTIONS = ["core_course_get_contents", "core_course_get_courses_by_field"]


class ConnectRequest(BaseModel):
    token: str = Field(min_length=1)


class ConnectResponse(BaseModel):
    status: str
    fullname: str
    username: str
    sitename: str
    release: str
    downloadfiles: bool
    missing_functions: list[str]


@contextmanager
def moodle_errors() -> Iterator[None]:
    try:
        yield
    except MoodleError as error:
        print(f"Moodle error: {error.errorcode}: {error.message}")
        if error.errorcode == "invalidtoken":
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid Moodle token") from error
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, f"Moodle error: {error.errorcode}"
        ) from error
    except httpx2.HTTPError as error:
        print(f"Moodle request failed: {error!r}")
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Moodle is unreachable") from error


@router.post("/connect")
async def connect(
    body: ConnectRequest,
    moodle: Annotated[MoodleClient, Depends(get_moodle_client)],
) -> ConnectResponse:
    print(f"Moodle token: {body.token}")

    with moodle_errors():
        info = await moodle.get_site_info(body.token)

    print(f"Moodle site info: {info.model_dump(exclude={'functions'})}")

    return ConnectResponse(
        status="connected",
        fullname=info.fullname,
        username=info.username,
        sitename=info.sitename,
        release=info.release,
        downloadfiles=bool(info.downloadfiles),
        missing_functions=[f for f in REQUIRED_FUNCTIONS if not info.has_function(f)],
    )


@router.get("/{course_id}")
async def get_course(
    course_id: int,
    moodle: Annotated[MoodleClient, Depends(get_moodle_client)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> Course:
    with moodle_errors():
        courses = await moodle.get_courses_by_field(
            settings.moodle_token, field="id", value=course_id
        )

    if not courses:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Course not found")

    print(f"Moodle course: {courses[0].model_dump()}")
    return courses[0]


def print_contents(course_id: int, sections: list[Section]) -> None:
    print(f"Moodle course {course_id} contents:")
    for section in sections:
        print(f"  Section {section.section}: {section.name} ({len(section.modules)} modules)")
        for module in section.modules:
            print(f"    [{module.modname}] {module.name}")
            for content in module.contents:
                size = f", {content.filesize} bytes" if content.filesize else ""
                print(f"      - {content.type}: {content.filename}{size} {content.fileurl}")


@router.get("/{course_id}/contents")
async def get_course_contents(
    course_id: int,
    moodle: Annotated[MoodleClient, Depends(get_moodle_client)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> list[Section]:
    with moodle_errors():
        sections = await moodle.get_course_contents(settings.moodle_token, course_id)

    print_contents(course_id, sections)
    return sections
