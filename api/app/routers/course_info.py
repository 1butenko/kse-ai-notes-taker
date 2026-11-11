import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, StringConstraints

from app.config import Settings, get_settings
from app.course import CourseInfo, load_info, save_info
from app.routers.plans import COURSE, course_dir

router = APIRouter(prefix="/course-info", tags=["course-info"])


class CourseInfoRequest(BaseModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]


@router.get("")
def list_course_info(settings: Annotated[Settings, Depends(get_settings)]) -> list[CourseInfo]:
    root = settings.uploads_dir
    if not root.is_dir():
        return []
    found = [load_info(d) for d in root.iterdir() if d.is_dir() and COURSE.match(d.name)]
    return sorted((i for i in found if i), key=lambda i: i.created_at, reverse=True)


@router.get("/{course}")
def get_course_info(
    course: str, settings: Annotated[Settings, Depends(get_settings)]
) -> CourseInfo:
    info = load_info(course_dir(settings, course))
    if info is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Course not found")
    return info


@router.put("/{course}")
def put_course_info(
    course: str, body: CourseInfoRequest, settings: Annotated[Settings, Depends(get_settings)]
) -> CourseInfo:
    directory = course_dir(settings, course)
    previous = load_info(directory)
    info = CourseInfo(
        course=course,
        name=body.name,
        created_at=previous.created_at if previous else datetime.now(UTC).isoformat(),
        readings_approved_at=previous.readings_approved_at if previous else None,
    )
    save_info(directory, info)
    return info


def approval(settings: Settings, course: str, approved_at: str | None) -> CourseInfo:
    directory = course_dir(settings, course)
    info = load_info(directory)
    if info is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Course not found")
    info = info.model_copy(update={"readings_approved_at": approved_at})
    save_info(directory, info)
    return info


@router.post("/{course}/readings-approval")
def approve_readings(
    course: str, settings: Annotated[Settings, Depends(get_settings)]
) -> CourseInfo:
    """The lecturer approved the readings per lecture."""
    return approval(settings, course, datetime.now(UTC).isoformat(timespec="seconds"))


@router.delete("/{course}/readings-approval")
def revoke_readings_approval(
    course: str, settings: Annotated[Settings, Depends(get_settings)]
) -> CourseInfo:
    return approval(settings, course, None)


def trash_dir(settings: Settings) -> Path:
    """Where Start over puts a course. Not a course key, so it is never listed."""
    return settings.uploads_dir / ".trash"


@router.delete("/{course}", status_code=status.HTTP_204_NO_CONTENT)
def delete_course(course: str, settings: Annotated[Settings, Depends(get_settings)]) -> None:
    """Start over: the course folder and its uploads move to the trash. Visual notes live in S3
    and Aurora and are not touched; a run going on keeps the readings it already read."""
    directory = course_dir(settings, course)
    if not directory.is_dir():
        return
    trash_dir(settings).mkdir(parents=True, exist_ok=True)
    target = trash_dir(settings) / f"{course}-{datetime.now(UTC):%Y%m%d-%H%M%S-%f}"
    shutil.move(directory, target)
    print(f"Moved course storage to the trash: {course} -> {target.name}")
