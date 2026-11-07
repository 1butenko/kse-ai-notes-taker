"""Where fetched materials are recorded: the `materials` table."""

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from app import db
from app.note_taker.moodle.catalog import CatalogSection


@dataclass(frozen=True)
class MaterialRecord:
    id: UUID
    course_id: UUID
    moodle_module_id: int
    name: str
    mimetype: str
    size: int
    s3_key: str
    source_url: str
    moodle_timemodified: int
    reason: str
    section: int = 0
    section_name: str = ""


class MaterialsStore(Protocol):
    def exists(self, course_id: UUID, source_url: str, timemodified: int) -> bool: ...

    def add(self, record: MaterialRecord) -> None: ...

    def save_topics(self, course_id: UUID, topics: list[CatalogSection]) -> None: ...


class PostgresMaterialsStore:
    def exists(self, course_id: UUID, source_url: str, timemodified: int) -> bool:
        with db.transaction() as conn:
            row = conn.execute(
                "SELECT 1 FROM materials"
                " WHERE course_id = %s AND source_url = %s AND moodle_timemodified = %s",
                (course_id, source_url, timemodified),
            ).fetchone()
        return row is not None

    def add(self, record: MaterialRecord) -> None:
        with db.transaction() as conn:
            conn.execute(
                "INSERT INTO materials (id, course_id, moodle_module_id, section, section_name,"
                " name, mimetype, size, s3_key, source_url, moodle_timemodified, reason)"
                " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
                " ON CONFLICT (course_id, source_url, moodle_timemodified) DO NOTHING",
                (
                    record.id,
                    record.course_id,
                    record.moodle_module_id,
                    record.section,
                    record.section_name,
                    record.name,
                    record.mimetype,
                    record.size,
                    record.s3_key,
                    record.source_url,
                    record.moodle_timemodified,
                    record.reason,
                ),
            )

    def save_topics(self, course_id: UUID, topics: list[CatalogSection]) -> None:
        with db.transaction() as conn:
            for topic in topics:
                conn.execute(
                    "INSERT INTO course_topics (course_id, section, name, summary)"
                    " VALUES (%s, %s, %s, %s)"
                    " ON CONFLICT (course_id, section)"
                    " DO UPDATE SET name = EXCLUDED.name, summary = EXCLUDED.summary",
                    (course_id, topic.section, topic.name, topic.summary),
                )
