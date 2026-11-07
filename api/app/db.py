"""PostgreSQL access for Aurora with IAM database authentication.

Express configuration clusters accept only IAM auth: the password is a 15-minute token
generated from the caller's AWS credentials, so a fresh token is made for every connection.
https://docs.aws.amazon.com/AmazonRDS/latest/AuroraUserGuide/UsingWithRDS.IAMDBAuth.html

Used only by the AI Note Taker (courses linked to Moodle, fetched materials, runs); the rest of
the app keeps its files in the uploads directory.
"""

import time
from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path
from typing import Any

import boto3
import psycopg
from psycopg.rows import dict_row

from app.config import get_settings

SCHEMA_PATH = Path(__file__).with_name("schema.sql")

# An auto-paused Aurora Serverless instance takes about 15 s to resume (30 s+ after a day
# idle), so wait longer than that and retry, as the Aurora auto-pause docs recommend.
CONNECT_TIMEOUT_SECONDS = 40
CONNECT_ATTEMPTS = 3


class DatabaseNotConfigured(RuntimeError):
    pass


@lru_cache
def _rds_client() -> Any:
    return boto3.client("rds", region_name=get_settings().aws_region)


def _auth_token() -> str:
    settings = get_settings()
    return _rds_client().generate_db_auth_token(
        DBHostname=settings.db_host,
        Port=settings.db_port,
        DBUsername=settings.db_user,
        Region=settings.aws_region,
    )


def connect() -> psycopg.Connection[dict[str, Any]]:
    settings = get_settings()
    if not settings.db_host:
        raise DatabaseNotConfigured("DB_HOST is not set; see .env.example")

    for attempt in range(1, CONNECT_ATTEMPTS + 1):
        try:
            return psycopg.connect(
                host=settings.db_host,
                port=settings.db_port,
                dbname=settings.db_name,
                user=settings.db_user,
                password=_auth_token(),
                sslmode="require",
                connect_timeout=CONNECT_TIMEOUT_SECONDS,
                row_factory=dict_row,
            )
        except psycopg.OperationalError:
            if attempt == CONNECT_ATTEMPTS:
                raise
            time.sleep(2 * attempt)
    raise AssertionError("unreachable")


@contextmanager
def transaction() -> Iterator[psycopg.Connection[dict[str, Any]]]:
    """Open a connection, commit on success, roll back on error, always close."""
    with connect() as conn:
        yield conn


def apply_schema() -> None:
    with transaction() as conn:
        conn.execute(SCHEMA_PATH.read_text(encoding="utf-8"))
