"""File digests, and the S3 key layout of the AI Note Taker's course files.

Every Note Taker course owns one prefix, `courses/<course-id>/`, stored in `courses.s3_prefix`.
The prefix uses the course UUID, not its title, so renaming a course never moves files.

    courses/<course-id>/course.json                       manifest (id, title, created_at)
    courses/<course-id>/materials/<file-id>/<file-name>   materials fetched from Moodle
    courses/<course-id>/lecture-notes/<session>/<run>/    a lecture-notes page: index.html,
                                                          index_files/, assets/, index.qmd
"""

import hashlib
import json
import mimetypes
import os
import re
import unicodedata
from functools import lru_cache
from pathlib import Path
from typing import Any, BinaryIO
from uuid import UUID, uuid4

import boto3

from app.config import get_settings

COURSES_ROOT = "courses/"
MANIFEST_NAME = "course.json"

# Characters S3 lists as safe in object keys; everything else becomes "-".
# https://docs.aws.amazon.com/AmazonS3/latest/userguide/object-keys.html
_UNSAFE_KEY_CHARS = re.compile(r"[^A-Za-z0-9!\-_.*'()]+")


def sha256(file: Path) -> str:
    with file.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def atomic_json(path: Path, value: Any) -> None:
    """Write JSON so a reader never sees a half-written file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}-{uuid4().hex}")
    try:
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2))
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def course_prefix(course_id: UUID) -> str:
    return f"{COURSES_ROOT}{course_id}/"


def manifest_key(course_id: UUID) -> str:
    return f"{course_prefix(course_id)}{MANIFEST_NAME}"


def safe_file_name(name: str) -> str:
    """Make a file name safe for an S3 key, keeping its extension readable."""
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    cleaned = _UNSAFE_KEY_CHARS.sub("-", ascii_name).strip("-.")
    return cleaned[:200] or "file"


def material_key(course_id: UUID, file_id: UUID, file_name: str) -> str:
    return f"{course_prefix(course_id)}materials/{file_id}/{safe_file_name(file_name)}"


def lecture_notes_prefix(course_id: UUID, session_id: str, run_id: UUID) -> str:
    return f"{course_prefix(course_id)}lecture-notes/{safe_file_name(session_id)}/{run_id}/"


@lru_cache
def s3_client() -> Any:
    return boto3.client("s3", region_name=get_settings().aws_region)


def upload_stream(key: str, fileobj: BinaryIO, content_type: str | None = None) -> None:
    """Stream a file-like object to S3 (multipart for large files) without buffering it all."""
    extra = {"ContentType": content_type} if content_type else {}
    s3_client().upload_fileobj(fileobj, get_settings().s3_bucket, key, ExtraArgs=extra)


def put_file(key: str, path: Path) -> None:
    """Upload one local file, with its content type from its name."""
    content_type, _ = mimetypes.guess_type(path.name)
    with path.open("rb") as f:
        upload_stream(key, f, content_type or "application/octet-stream")


def get_object(key: str) -> dict[str, Any]:
    """An object's body (streaming) and metadata."""
    return s3_client().get_object(Bucket=get_settings().s3_bucket, Key=key)


def presigned_url(key: str, expires_in: int = 3600) -> str:
    """A temporary download link for one object."""
    return s3_client().generate_presigned_url(
        "get_object",
        Params={"Bucket": get_settings().s3_bucket, "Key": key},
        ExpiresIn=expires_in,
    )


def write_manifest(course: dict[str, Any]) -> None:
    """Write courses/<id>/course.json so the bucket alone shows which course a prefix holds."""
    body = json.dumps(
        {
            "id": str(course["id"]),
            "title": course["title"],
            "created_at": course["created_at"].isoformat(),
        },
        ensure_ascii=False,
        indent=2,
    )
    s3_client().put_object(
        Bucket=get_settings().s3_bucket,
        Key=manifest_key(course["id"]),
        Body=body.encode(),
        ContentType="application/json",
    )
