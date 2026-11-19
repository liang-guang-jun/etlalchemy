"""Persistence helpers shared by every read-model implementation.

Every bounded context materialises its events into its own SQLAlchemy view, and
that view has to do the same five things: build the tracking table, run the DML
and its tracking row in one transaction, read rows, read one row, and add a
column to a table that predates it. Those five things were copied into eight
modules; they live here instead.

Only the standard library and ``eventsourcing`` are imported: the dialect upsert
comes from :meth:`AsyncSQLAlchemyTrackingRecorder._dialect_insert`, so this
module never imports SQLAlchemy itself.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from eventsourcing.asyncio.sqlalchemy import (
    AsyncSQLAlchemyDatastore,
    AsyncSQLAlchemyTrackingRecorder,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from eventsourcing.persistence import Tracking
    from sqlalchemy import MetaData

__all__ = ["AsyncCoreView", "ensure_column", "utc_now"]


def utc_now() -> datetime:
    """Returns the current UTC timestamp written by soft deletes."""
    return datetime.now(UTC)


class AsyncCoreView(AsyncSQLAlchemyTrackingRecorder):
    """Tracking recorder with the DML helpers every read model needs.

    A subclass sets :attr:`view_metadata` to the ``MetaData`` of its own tables
    and implements the abstract methods of its read-model interface. The helpers
    keep the view change and its tracking record in one transaction, which is
    what makes replaying an already applied notification roll back instead of
    corrupting the view.
    """

    view_metadata: MetaData
    """Definitions of the tables this view owns, created by :meth:`create_table`."""

    async def create_table(self) -> None:
        """Creates the view tables and the tracking table if they do not exist."""
        async with self.datastore.transaction() as conn:
            await conn.run_sync(self.view_metadata.create_all)
            await conn.run_sync(self.datastore.metadata.create_all)
            await self.migrate(conn)

    async def migrate(self, conn: Any) -> None:
        """Adds columns an existing table predates.

        The hook runs inside the transaction of :meth:`create_table`, so a
        context that grew a column overrides it and calls :func:`ensure_column`.

        Args:
            conn: Connection of the surrounding transaction.
        """

    async def _write(self, statements: Sequence[Any], tracking: Tracking) -> None:
        """Applies the statements and records the tracking row atomically.

        Args:
            statements: DML statements built by the caller, applied in order.
            tracking: Position recorded with the change.
        """
        async with self.transaction() as conn:
            for statement in statements:
                await conn.execute(statement)
            await self.insert_tracking_in_transaction(conn, tracking)

    async def _fetch_all(self, statement: Any) -> Sequence[Any]:
        """Executes a read statement and returns all rows."""
        async with self.datastore.connection() as conn:
            rows: Sequence[Any] = (await conn.execute(statement)).all()
            return rows

    async def _fetch_one(self, statement: Any) -> Any:
        """Executes a read statement and returns the first row, or ``None``."""
        async with self.datastore.connection() as conn:
            return (await conn.execute(statement)).first()


async def ensure_column(
    conn: Any,
    dialect: str,
    table: str,
    column: str,
    definition: str,
) -> None:
    """Adds one column to a view table when an older layout lacks it.

    SQLite has no ``ADD COLUMN IF NOT EXISTS``, so its table layout is inspected
    first; PostgreSQL accepts the idempotent form directly.

    Args:
        conn: Connection of the surrounding transaction.
        dialect: ``datastore.dialect_name`` of the running backend.
        table: Name of the view table.
        column: Name of the column to add.
        definition: Column type and default, appended to ``ADD COLUMN``.
    """
    if dialect == AsyncSQLAlchemyDatastore.SQLITE:
        result = await conn.exec_driver_sql(f"PRAGMA table_info({table})")
        existing = {str(row._mapping["name"]) for row in result.fetchall()}
        if column not in existing:
            await conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
        return
    await conn.exec_driver_sql(
        f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {definition}"
    )
