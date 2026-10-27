import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, StringConstraints, ValidationError

from app.config import Settings, get_settings
from app.routers.plans import COURSE, course_dir

router = APIRouter(prefix="/course-info", tags=["course-info"])


class CourseInfo(BaseModel):
    course: str
    name: str
    created_at: str


class CourseInfoRequest(BaseModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]


def info_file(directory: Path) -> Path:
    return directory / "course.json"


def load_info(directory: Path) -> CourseInfo | None:
    target = info_file(directory)
    if not target.is_file():
        return None
    try:
        info = CourseInfo.model_validate_json(target.read_text())
    except ValidationError:
        return None
    # The directory names the course, whatever the file says.
    return info.model_copy(update={"course": directory.name})


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
    )
    directory.mkdir(parents=True, exist_ok=True)
    info_file(directory).write_text(info.model_dump_json(indent=2))
    return info


@router.delete("/{course}", status_code=status.HTTP_204_NO_CONTENT)
def delete_course(course: str, settings: Annotated[Settings, Depends(get_settings)]) -> None:
    """Start over: everything stored for the course goes, uploads and notes included."""
    directory = course_dir(settings, course)
    if directory.is_dir():
        shutil.rmtree(directory)
    print(f"Deleted course storage: {course}")
