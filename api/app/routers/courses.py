from typing import Annotated

import httpx2
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.moodle import MoodleClient, MoodleError, get_moodle_client

router = APIRouter(prefix="/courses", tags=["courses"])

REQUIRED_FUNCTIONS = ["core_course_get_contents"]


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


@router.post("/connect")
async def connect(
    body: ConnectRequest,
    moodle: Annotated[MoodleClient, Depends(get_moodle_client)],
) -> ConnectResponse:
    print(f"Moodle token: {body.token}")

    try:
        info = await moodle.get_site_info(body.token)
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
