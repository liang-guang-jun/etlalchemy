"""Helpers shared by the asynchronous test suite."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import quote, urlparse


def sqlite_url(path: Path) -> str:
    """Returns the async SQLAlchemy URL of a temporary SQLite file."""
    return f"sqlite+aiosqlite:///{path}"


def async_postgres_url(dsn: str) -> str:
    """Returns the async SQLAlchemy URL of the given PostgreSQL DSN."""
    parsed = urlparse(dsn)
    credentials = ""
    if parsed.username:
        user = quote(parsed.username, safe="")
        password = quote(parsed.password or "", safe="")
        credentials = f"{user}:{password}@"
    host = parsed.hostname or "localhost"
    port = parsed.port or 5432
    return f"postgresql+psycopg://{credentials}{host}:{port}{parsed.path}"


def async_env(url: str) -> dict[str, str]:
    """Returns an eventsourcing environment for the asyncio SQLAlchemy module."""
    return {
        "PERSISTENCE_MODULE": "etlalchemy._vendor.eventsourcing.asyncio.sqlalchemy",
        "SQLALCHEMY_URL": url,
        "CREATE_TABLE": "y",
    }
