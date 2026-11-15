"""Durable LangGraph checkpointer selected from the database settings.

LangGraph owns the shape of its own ``checkpoints`` and ``checkpoint_writes``
tables, so they are the one documented exception to the ``<context>_<plural>``
naming rule. The tables are created on first use by ``setup()``.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

from etlalchemy.shared.logging import get_logger


@dataclass(frozen=True)
class CheckpointSettings:
    """Where the durable graph checkpoints live."""

    backend: str = "none"
    """One of ``sqlite``, ``postgres`` or ``none`` to disable checkpointing."""
    sqlite_path: str = "./catalog.db"
    """SQLite file used by the ``sqlite`` backend."""
    postgres_dsn: str = ""
    """PostgreSQL DSN used by the ``postgres`` backend, with the plain driver."""

    @property
    def enabled(self) -> bool:
        """Returns whether a durable checkpointer is configured."""
        return self.backend != "none"


@asynccontextmanager
async def open_checkpointer(
    settings: CheckpointSettings,
) -> AsyncIterator[Any | None]:
    """Opens the configured checkpointer for the lifetime of the process.

    Args:
        settings: Backend and connection details.

    Yields:
        The checkpointer, or ``None`` when checkpointing is disabled.

    Raises:
        ValueError: If the backend is not one of the supported values.
    """
    log = get_logger("agent.checkpoint")
    if settings.backend == "none":
        log.warning("agent.checkpoint.disabled")
        yield None
        return
    if settings.backend == "sqlite":
        from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

        async with AsyncSqliteSaver.from_conn_string(settings.sqlite_path) as saver:
            await saver.setup()
            log.info("agent.checkpoint.ready", backend="sqlite")
            yield saver
        return
    if settings.backend == "postgres":
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

        async with AsyncPostgresSaver.from_conn_string(settings.postgres_dsn) as saver:
            await saver.setup()
            log.info("agent.checkpoint.ready", backend="postgres")
            yield saver
        return
    msg = f"unknown checkpoint backend {settings.backend!r}"
    raise ValueError(msg)
