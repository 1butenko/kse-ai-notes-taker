"""The course in the app (uploads folder, syllabus transcript, lecture plan), reached through the
API's own endpoints: the agent saves files, reads the syllabus and maps readings exactly as the
lecturer's screens do, with the same checks.
"""

from typing import Any, Literal

import httpx

from app.worker.config import get_worker_settings

Category = Literal["syllabus", "reading"]

SYLLABUS_SUFFIXES = (".pdf", ".docx")


class ProjectError(Exception):
    pass


class Project:
    """One course of the app, by its key (the Moodle course id)."""

    def __init__(self, course: str, http: httpx.Client) -> None:
        self.course = course
        self.http = http

    @classmethod
    def connect(cls, course: str) -> "Project":
        settings = get_worker_settings()
        # Reading a syllabus or mapping books takes minutes: bound connecting only.
        http = httpx.Client(base_url=settings.api_url, timeout=httpx.Timeout(900, connect=10))
        return cls(course, http)

    def call(self, method: str, path: str, **kwargs: Any) -> Any:
        try:
            reply = self.http.request(method, path, **kwargs)
        except httpx.HTTPError as error:
            raise ProjectError(f"The app's API is unreachable: {error}") from error
        if reply.is_error:
            try:
                detail = reply.json()["detail"]
            except (ValueError, KeyError, TypeError):
                detail = reply.text[:300] or f"HTTP {reply.status_code}"
            raise ProjectError(str(detail))
        return None if reply.status_code == 204 else reply.json()

    def save_files(self, category: Category, files: list[tuple[str, str]]) -> list[dict]:
        """Download Moodle files (file URL, file name) into the course's syllabus or readings."""
        return self.call(
            "POST",
            "/uploads/moodle",
            json={
                "category": category,
                "course_id": int(self.course),
                "files": [{"fileurl": url, "filename": name} for url, name in files],
            },
        )

    def save_link(self, module_id: int) -> list[dict]:
        """Save the web page a Moodle link points to as a reading (PDF, or the page as text)."""
        return self.call(
            "POST",
            "/uploads/moodle/links",
            json={"course_id": int(self.course), "modules": [module_id]},
        )

    def files(self) -> dict[str, list[dict]]:
        return self.call("GET", f"/uploads/{self.course}")

    def plan(self) -> dict:
        return self.call("GET", f"/plans/{self.course}")

    def syllabus_path(self) -> str | None:
        """The course's syllabus: the plan's, or else its first PDF or DOCX syllabus file."""
        primary = self.plan().get("primary")
        if primary:
            return primary
        for file in self.files()["syllabus"]:
            if file["path"].lower().endswith(SYLLABUS_SUFFIXES):
                return file["path"]
        return None

    def read_syllabus(self, path: str) -> dict:
        """Read the syllabus into lectures and make it the course plan."""
        transcript = self.call("POST", "/syllabus/transcribe", json={"path": path})
        if self.plan().get("primary") != path:
            self.call("PUT", f"/plans/{self.course}/primary", json={"path": path})
        return transcript

    def map_readings(self) -> dict:
        """Match the cited books to the reading files and approve what was found, as the
        course page's automatic matching does: estimated pages stay marked for a check."""
        self.call("POST", f"/plans/{self.course}/map")
        plan = self.call("POST", f"/plans/{self.course}/proposals/approve-all")
        for session in plan["sessions"]:
            for proposal in session["proposals"]:
                if (
                    proposal["status"] == "proposed"
                    and proposal.get("method") == "toc"
                    and proposal.get("pdf_start") is not None
                    and proposal.get("pdf_end") is not None
                ):
                    plan = self.call(
                        "POST",
                        f"/plans/{self.course}/proposals/{proposal['id']}/approve",
                        json={"pdf_start": proposal["pdf_start"], "pdf_end": proposal["pdf_end"]},
                    )
        return plan

    def attach(self, session_id: str, path: str) -> dict:
        return self.call(
            "POST", f"/plans/{self.course}/sessions/{session_id}/files", json={"path": path}
        )
