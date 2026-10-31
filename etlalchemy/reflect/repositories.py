"""Reflection caches: the protocol every cache implements, plus four stores.

``JsonReflectionRepository`` writes one JSON file per cache key and replaces
the file atomically. ``YamlReflectionRepository`` writes the same payload as
YAML, ``InMemoryReflectionRepository`` keeps it in a dict, and
``SqlAlchemyReflectionRepository`` stores it in a table of an existing engine.

Every repository takes its storage explicitly: file repositories take a
directory, the SQLAlchemy repository takes an engine, and the in-memory
repository takes nothing. There is no default cache directory.
"""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

import sqlalchemy as sa
from sqlalchemy.engine import Engine

from etlalchemy.reflect.serialization import (
    payload_complete,
    tables_from_payload,
    tables_to_payload,
)
from etlalchemy.reflect.table import ReflectedTable


@runtime_checkable
class ReflectionRepository(Protocol):
    """Storage for reflected tables, keyed by connection and selection.

    ``get`` returns the cached tables, while ``get_entry`` also returns whether
    the entry came from a complete reflection. ``save`` overwrites the entry of
    a key, and ``clear`` removes it. ``complete=False`` marks a partial
    reflection, so the next session keeps reflecting the missing tables.
    """

    def get(self, key: str) -> tuple[ReflectedTable, ...] | None:
        """Return the tables cached under ``key``, if any."""
        ...

    def get_entry(self, key: str) -> tuple[tuple[ReflectedTable, ...], bool] | None:
        """Return the tables and the ``complete`` flag cached under ``key``."""
        ...

    def save(
        self,
        key: str,
        tables: tuple[ReflectedTable, ...],
        *,
        complete: bool,
    ) -> None:
        """Store ``tables`` under ``key``, replacing any previous entry."""
        ...

    def clear(self, key: str) -> None:
        """Remove the entry stored under ``key``."""
        ...


class InMemoryReflectionRepository:
    """Keep reflected tables in memory for the lifetime of the process."""

    def __init__(self) -> None:
        """Start with an empty cache."""
        self._entries: dict[str, tuple[tuple[ReflectedTable, ...], bool]] = {}

    def get(self, key: str) -> tuple[ReflectedTable, ...] | None:
        """Return the tables cached under ``key``, if any."""
        entry = self._entries.get(key)
        return None if entry is None else entry[0]

    def get_entry(self, key: str) -> tuple[tuple[ReflectedTable, ...], bool] | None:
        """Return the tables and the ``complete`` flag cached under ``key``."""
        return self._entries.get(key)

    def save(
        self,
        key: str,
        tables: tuple[ReflectedTable, ...],
        *,
        complete: bool,
    ) -> None:
        """Store ``tables`` under ``key``, replacing any previous entry."""
        self._entries[key] = (tables, complete)

    def clear(self, key: str) -> None:
        """Remove the entry stored under ``key``."""
        self._entries.pop(key, None)

    def __len__(self) -> int:
        """Return the number of cached entries."""
        return len(self._entries)


class _FileReflectionRepository:
    """Share the file handling of the JSON and YAML repositories."""

    _suffix = ".json"

    def __init__(self, directory: Path | None = None) -> None:
        """Keep the directory the cache files are written to.

        Raises:
            ValueError: If ``directory`` is not given.
        """
        if directory is None:
            raise ValueError(
                f"{type(self).__name__} requires an explicit directory; pass the "
                "directory the cache files should be written to"
            )
        self._directory = Path(directory)

    def get(self, key: str) -> tuple[ReflectedTable, ...] | None:
        """Return the tables cached under ``key``, if any."""
        entry = self.get_entry(key)
        return None if entry is None else entry[0]

    def get_entry(self, key: str) -> tuple[tuple[ReflectedTable, ...], bool] | None:
        """Return the tables and the ``complete`` flag cached under ``key``."""
        try:
            text = self._path(key).read_text(encoding="utf-8")
        except OSError:
            return None
        try:
            payload: Any = self._loads(text)
        except ValueError:
            return None
        if not isinstance(payload, Mapping):
            return None
        tables = tables_from_payload(payload)
        if tables is None:
            return None
        return tables, payload_complete(payload)

    def save(
        self,
        key: str,
        tables: tuple[ReflectedTable, ...],
        *,
        complete: bool,
    ) -> None:
        """Write ``tables`` under ``key`` with an atomic file replacement."""
        self._directory.mkdir(parents=True, exist_ok=True)
        payload = self._dumps(tables_to_payload(tables, complete=complete))
        handle, temporary = tempfile.mkstemp(
            dir=self._directory,
            suffix=self._suffix,
        )
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as stream:
                stream.write(payload)
            os.replace(temporary, self._path(key))
        except BaseException:
            Path(temporary).unlink(missing_ok=True)
            raise

    def clear(self, key: str) -> None:
        """Remove the cache file of ``key``."""
        self._path(key).unlink(missing_ok=True)

    def _path(self, key: str) -> Path:
        """Return the cache file of one key."""
        return self._directory / f"{key}{self._suffix}"

    def _dumps(self, payload: dict[str, object]) -> str:
        """Serialise a payload to text."""
        raise NotImplementedError

    def _loads(self, text: str) -> object:
        """Parse a payload from text."""
        raise NotImplementedError


class JsonReflectionRepository(_FileReflectionRepository):
    """Store one JSON file per cache key, atomically replaced on save."""

    _suffix = ".json"

    def _dumps(self, payload: dict[str, object]) -> str:
        """Serialise a payload as indented JSON."""
        return json.dumps(payload, indent=2)

    def _loads(self, text: str) -> object:
        """Parse JSON text, raising ``ValueError`` on invalid input."""
        return json.loads(text)


class YamlReflectionRepository(_FileReflectionRepository):
    """Store one YAML file per cache key, atomically replaced on save."""

    _suffix = ".yaml"

    def __init__(self, directory: Path | None = None) -> None:
        """Import PyYAML and keep the cache directory.

        Raises:
            ImportError: If PyYAML is not installed.
            ValueError: If ``directory`` is not given.
        """
        try:
            import yaml
        except ImportError as exc:  # pragma: no cover - depends on the environment
            raise ImportError(
                "PyYAML is required for the YAML reflection cache; install "
                "etlalchemy[yaml] or pyyaml"
            ) from exc
        self._yaml: Any = yaml
        super().__init__(directory)

    def _dumps(self, payload: dict[str, object]) -> str:
        """Serialise a payload as YAML."""
        return str(self._yaml.safe_dump(payload))

    def _loads(self, text: str) -> object:
        """Parse YAML text, raising ``ValueError`` on invalid input."""
        try:
            return self._yaml.safe_load(text)
        except self._yaml.YAMLError as exc:
            raise ValueError(str(exc)) from exc


class SqlAlchemyReflectionRepository:
    """Store reflected tables in a table of an existing SQLAlchemy engine."""

    def __init__(
        self,
        engine: Engine,
        table_name: str = "etlalchemy_reflect_cache",
    ) -> None:
        """Keep the engine and declare the cache table."""
        self._engine = engine
        self._metadata = sa.MetaData()
        self._table = sa.Table(
            table_name,
            self._metadata,
            sa.Column("key", sa.Text, primary_key=True),
            sa.Column("complete", sa.Boolean, nullable=False),
            sa.Column("payload", sa.Text, nullable=False),
            sa.Column("updated_at", sa.DateTime, nullable=False),
        )
        self._ready = False

    def get(self, key: str) -> tuple[ReflectedTable, ...] | None:
        """Return the tables cached under ``key``, if any."""
        entry = self.get_entry(key)
        return None if entry is None else entry[0]

    def get_entry(self, key: str) -> tuple[tuple[ReflectedTable, ...], bool] | None:
        """Return the tables and the ``complete`` flag cached under ``key``."""
        self._ensure_schema()
        with self._engine.connect() as connection:
            row = connection.execute(
                sa.select(self._table.c.complete, self._table.c.payload).where(
                    self._table.c.key == key
                )
            ).first()
        if row is None:
            return None
        try:
            payload: Any = json.loads(row.payload)
        except ValueError:
            return None
        if not isinstance(payload, Mapping):
            return None
        tables = tables_from_payload(payload)
        if tables is None:
            return None
        return tables, bool(row.complete)

    def save(
        self,
        key: str,
        tables: tuple[ReflectedTable, ...],
        *,
        complete: bool,
    ) -> None:
        """Insert or update the row of ``key``."""
        self._ensure_schema()
        payload = json.dumps(tables_to_payload(tables, complete=complete))
        updated_at = datetime.now(UTC)
        with self._engine.begin() as connection:
            exists = connection.execute(
                sa.select(self._table.c.key).where(self._table.c.key == key)
            ).first()
            if exists is None:
                connection.execute(
                    sa.insert(self._table).values(
                        key=key,
                        complete=complete,
                        payload=payload,
                        updated_at=updated_at,
                    )
                )
            else:
                connection.execute(
                    sa.update(self._table)
                    .where(self._table.c.key == key)
                    .values(
                        complete=complete,
                        payload=payload,
                        updated_at=updated_at,
                    )
                )

    def clear(self, key: str) -> None:
        """Delete the row of ``key``."""
        self._ensure_schema()
        with self._engine.begin() as connection:
            connection.execute(sa.delete(self._table).where(self._table.c.key == key))

    def _ensure_schema(self) -> None:
        """Create the cache table on first use."""
        if not self._ready:
            self._metadata.create_all(self._engine)
            self._ready = True


__all__ = [
    "InMemoryReflectionRepository",
    "JsonReflectionRepository",
    "ReflectionRepository",
    "SqlAlchemyReflectionRepository",
    "YamlReflectionRepository",
]
