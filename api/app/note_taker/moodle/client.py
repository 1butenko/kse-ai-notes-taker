"""Synchronous Moodle REST web-service client (ported from the pre-reset `app/moodle.py`)."""

import json
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import httpx
from pydantic import BaseModel


class MoodleError(Exception):
    def __init__(self, errorcode: str, message: str) -> None:
        super().__init__(f"{errorcode}: {message}")
        self.errorcode = errorcode
        self.message = message


class ModuleContent(BaseModel):
    type: str = "file"
    filename: str = ""
    fileurl: str = ""
    filesize: int = 0
    mimetype: str = ""
    timemodified: int = 0


class Module(BaseModel):
    id: int
    name: str
    modname: str
    url: str = ""
    description: str = ""
    visible: int = 1
    uservisible: bool = True
    contents: list[ModuleContent] = []


class Section(BaseModel):
    id: int
    section: int = 0
    name: str = ""
    summary: str = ""
    visible: int = 1
    modules: list[Module] = []


class MoodleClient:
    """Calls the Moodle web services with one user token, scoped to one Moodle site."""

    def __init__(self, base_url: str, token: str, http: httpx.Client | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.http = http or httpx.Client(timeout=30, follow_redirects=True)

    @property
    def endpoint(self) -> str:
        return f"{self.base_url}/webservice/rest/server.php"

    def _require_config(self) -> None:
        if not self.base_url or not self.token:
            raise MoodleError("notconfigured", "MOODLE_URL and MOODLE_TOKEN must be set")

    def call(self, wsfunction: str, **params: Any) -> Any:
        self._require_config()
        response = self.http.post(
            self.endpoint,
            data={
                "wstoken": self.token,
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

    def get_course_contents(self, moodle_course_id: int) -> list[Section]:
        payload = self.call("core_course_get_contents", courseid=moodle_course_id)
        return [Section.model_validate(item) for item in payload]

    @contextmanager
    def _open(self, fileurl: str) -> Iterator[httpx.Response]:
        self._require_config()
        url = httpx.URL(fileurl).copy_merge_params({"token": self.token})
        with self.http.stream("GET", url) as response:
            response.raise_for_status()
            yield response

    def iter_download(self, fileurl: str) -> Iterator[bytes]:
        """Stream a Moodle file's bytes. Raises MoodleError when Moodle answers with a JSON error.

        Moodle reports an invalid token or missing permission as a JSON body with HTTP 200, which
        would otherwise be stored as if it were the file.
        """
        with self._open(fileurl) as response:
            if "application/json" in response.headers.get("content-type", ""):
                payload = json.loads(response.read())
                raise MoodleError(payload.get("errorcode", "unknown"), payload.get("message", ""))
            yield from response.iter_bytes()

    def get_page_html(self, fileurl: str) -> str:
        """The HTML of a `page` or `book` content file."""
        return b"".join(self.iter_download(fileurl)).decode("utf-8", errors="replace")
