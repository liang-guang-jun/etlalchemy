"""Reflect tables of an external database, with an optional cache."""

from __future__ import annotations

from etlalchemy.reflect.inspector import ReflectionSession
from etlalchemy.reflect.repositories import (
    InMemoryReflectionRepository,
    ReflectionRepository,
)
from etlalchemy.reflect.source import ReflectSource
from etlalchemy.reflect.table import ReflectedTable


def _schema_argument(catalog: str | None, schema: str | None) -> str | None:
    """Return the schema argument to pass to the SQLAlchemy inspector.

    A catalog and a schema are joined as ``catalog.schema``; with only one of
    them, that value is used as is.
    """
    if catalog is not None and schema is not None:
        return f"{catalog}.{schema}"
    return catalog or schema


class Reflector:
    """Reflect tables of one source, caching them in a repository.

    The reflector holds the source and the repository, so several calls share
    one cache. It never connects to the database when it is built: every call
    opens a :class:`~etlalchemy.reflect.inspector.ReflectionSession`, which
    reflects only what the call needs.

    Both are optional: with neither, ``Reflector()`` reflects the database the
    runtime already knows about — a Databricks notebook, the ``DATABRICKS_*``
    variables, or the ``DEFAULT`` CLI profile — and caches in memory. Pass a
    source to name the connection, and a file or SQL repository to persist the
    cache.
    """

    def __init__(
        self,
        source: ReflectSource | None = None,
        repository: ReflectionRepository | None = None,
    ) -> None:
        """Keep ``source`` and the caller-provided ``repository``.

        When ``source`` is ``None``, an auto-detecting
        :class:`~etlalchemy.reflect.source.ReflectSource` is created, so
        ``Reflector()`` finds the notebook runtime, the ``DATABRICKS_*``
        variables or the ``DEFAULT`` CLI profile on its own.

        When ``repository`` is ``None``, an
        :class:`~etlalchemy.reflect.repositories.InMemoryReflectionRepository`
        is created, so a call without a cache still works and shares the cache
        across the calls made on the same reflector.
        """
        self._source = ReflectSource() if source is None else source
        self._repository = (
            InMemoryReflectionRepository() if repository is None else repository
        )

    @property
    def source(self) -> ReflectSource:
        """Return the reflected source."""
        return self._source

    @property
    def repository(self) -> ReflectionRepository:
        """Return the repository the reflector caches in."""
        return self._repository

    def table(
        self,
        name: str,
        *,
        catalog: str | None = None,
        schema: str | None = None,
        force: bool = False,
    ) -> ReflectedTable:
        """Reflect one table.

        Args:
            name: Table to reflect.
            catalog: Optional catalog passed to the inspector.
            schema: Optional schema passed to the inspector.
            force: Clear the cached entry before reflecting.

        Returns:
            The reflected table.
        """
        with self.session(
            catalog=catalog,
            schema=schema,
            table_names=(name,),
            force=force,
        ) as session:
            return session.table(name)

    def tables(
        self,
        names: tuple[str, ...],
        *,
        catalog: str | None = None,
        schema: str | None = None,
        force: bool = False,
    ) -> tuple[ReflectedTable, ...]:
        """Reflect the given tables, sorted by name.

        An empty ``names`` reflects every table of the schema.

        Args:
            names: Tables to reflect.
            catalog: Optional catalog passed to the inspector.
            schema: Optional schema passed to the inspector.
            force: Clear the cached entry before reflecting.

        Returns:
            The reflected tables, sorted by name.
        """
        selection = tuple(sorted(set(names)))
        with self.session(
            catalog=catalog,
            schema=schema,
            table_names=selection,
            force=force,
        ) as session:
            return session.tables()

    def all_tables(
        self,
        *,
        catalog: str | None = None,
        schema: str | None = None,
        force: bool = False,
    ) -> tuple[ReflectedTable, ...]:
        """Reflect every table the source selects, sorted by name.

        Args:
            catalog: Optional catalog passed to the inspector.
            schema: Optional schema passed to the inspector.
            force: Clear the cached entry before reflecting.

        Returns:
            The reflected tables, sorted by name.
        """
        with self.session(
            catalog=catalog,
            schema=schema,
            table_names=(),
            force=force,
        ) as session:
            return session.tables()

    def session(
        self,
        *,
        catalog: str | None = None,
        schema: str | None = None,
        table_names: tuple[str, ...] = (),
        force: bool = False,
    ) -> ReflectionSession:
        """Return a reflection session over this source and repository.

        Args:
            catalog: Optional catalog passed to the inspector.
            schema: Optional schema passed to the inspector.
            table_names: Tables the session may reflect; empty means every
                table of the schema.
            force: Clear the cached entry when the session starts.

        Returns:
            A session that reflects on demand and caches on close.
        """
        return ReflectionSession(
            self._source,
            repository=self._repository,
            catalog=catalog,
            schema=schema,
            table_names=table_names,
            force=force,
        )


__all__ = ["Reflector"]
