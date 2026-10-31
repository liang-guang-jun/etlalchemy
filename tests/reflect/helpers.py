"""Reflection helpers shared by the reflect tests."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import sqlalchemy as sa
from etlalchemy.reflect import (
    InMemoryReflectionRepository,
    ReflectedColumn,
    ReflectedTable,
    ReflectSource,
    reflect_tables,
)
from etlalchemy.semantic.types import Integer


def reflected_tables(
    source: ReflectSource,
    **kwargs: Any,
) -> tuple[ReflectedTable, ...]:
    """Reflect ``source`` into a throwaway in-memory repository."""
    return reflect_tables(
        source,
        repository=InMemoryReflectionRepository(),
        **kwargs,
    )


def sqlite_source(tmp_path: Path) -> ReflectSource:
    """Create a two-table SQLite database and return its reflection source."""
    path = tmp_path / "shop.db"
    engine = sa.create_engine(f"sqlite:///{path}")
    metadata = sa.MetaData()
    sa.Table(
        "users",
        metadata,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(20), nullable=False),
        sa.Column("balance", sa.Numeric(10, 2)),
        sa.Column("created_at", sa.DateTime),
        sa.Column("active", sa.Boolean),
        sa.Column("avatar", sa.LargeBinary(16)),
    )
    sa.Table(
        "orders",
        metadata,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("user_id", sa.Integer),
        sa.Column("total", sa.Float),
    )
    metadata.create_all(engine)
    engine.dispose()
    return ReflectSource(connection_url=f"sqlite:///{path}")


def add_table(source: ReflectSource, name: str) -> None:
    """Add one table to the SQLite database behind ``source``."""
    assert source.connection_url is not None
    engine = sa.create_engine(source.connection_url)
    metadata = sa.MetaData()
    sa.Table(name, metadata, sa.Column("id", sa.Integer, primary_key=True))
    metadata.create_all(engine)
    engine.dispose()


class RecordingInspector:
    """Stand in for ``LiveInspector`` and record how a session uses it.

    It mirrors the duck-typed contract of the live inspector — ``table_names``,
    ``table`` and ``close`` — so the reflect tests share one definition of it.
    """

    def __init__(
        self,
        names: tuple[str, ...] = ("alpha", "beta"),
        source: ReflectSource | None = None,
    ) -> None:
        """Serve ``names`` and start with nothing recorded."""
        self.names = names
        self.source = source
        self.schemas: list[str | None] = []
        self.calls: list[str] = []
        self.closed = False

    def table_names(self, schema: str | None) -> tuple[str, ...]:
        """Record the schema and return the fixed table names."""
        self.schemas.append(schema)
        self.calls.append(f"names:{schema}")
        return self.names

    def table(self, name: str, schema: str | None) -> ReflectedTable:
        """Record the call and return a one-column table."""
        self.calls.append(f"table:{name}:{schema}")
        return ReflectedTable(
            name=name,
            columns=(
                ReflectedColumn(name="id", sa_type=Integer(), nullable=False),
            ),
            primary_key=("id",),
        )

    def close(self) -> None:
        """Record that the inspector was closed."""
        self.closed = True
        self.calls.append("close")


class RecordingRepository(InMemoryReflectionRepository):
    """In-memory cache that records the keys it saved and cleared."""

    def __init__(self) -> None:
        """Start empty and with nothing recorded."""
        super().__init__()
        self.saved: list[tuple[str, bool]] = []
        self.cleared: list[str] = []

    def save(
        self,
        key: str,
        tables: tuple[ReflectedTable, ...],
        *,
        complete: bool,
    ) -> None:
        """Record the entry before storing it."""
        self.saved.append((key, complete))
        super().save(key, tables, complete=complete)

    def clear(self, key: str) -> None:
        """Record the key before clearing it."""
        self.cleared.append(key)
        super().clear(key)


class SessionSpy:
    """Stand in for ``ReflectionSession`` and record how it is driven.

    ``ReflectionSession`` is constructed by the reflector itself, so the spy
    keeps its instances in :attr:`instances` and the tables :meth:`tables`
    returns in :attr:`next_tables`; call :meth:`reset` before each test.
    """

    instances: list[SessionSpy] = []
    next_tables: tuple[ReflectedTable, ...] = ()

    def __init__(self, source: object = None, **kwargs: Any) -> None:
        """Record the table selection of this session."""
        self.table_names: tuple[str, ...] | None = kwargs.get("table_names")
        self.calls: list[tuple[str, ...]] = []
        SessionSpy.instances.append(self)

    @classmethod
    def reset(cls, tables: tuple[ReflectedTable, ...] = ()) -> None:
        """Forget the recorded sessions and the tables to return."""
        cls.instances = []
        cls.next_tables = tables

    def __enter__(self) -> SessionSpy:
        """Return the spy itself."""
        return self

    def __exit__(self, *exc_info: object) -> None:
        """Leave the ``with`` block without raising."""

    def tables(self) -> tuple[ReflectedTable, ...]:
        """Record the call and return the configured tables."""
        self.calls.append(("tables",))
        return SessionSpy.next_tables

    def table(self, name: str) -> ReflectedTable:
        """Record the call and return one one-column table."""
        self.calls.append(("table", name))
        return ReflectedTable(
            name=name,
            columns=(
                ReflectedColumn(name="id", sa_type="INTEGER", nullable=False),
            ),
            primary_key=("id",),
        )
