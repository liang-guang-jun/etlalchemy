"""Reflect tables of an external database, with an optional cache."""

from __future__ import annotations

from etlalchemy.reflect.inspector import ReflectionSession
from etlalchemy.reflect.repositories import ReflectionRepository
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
    reflects only what the call needs. The reflector never builds a default
    cache; a repository is required.
    """

    def __init__(
        self,
        source: ReflectSource,
        repository: ReflectionRepository | None = None,
    ) -> None:
        """Keep ``source`` and the caller-provided ``repository``.

        Raises:
            ValueError: If ``repository`` is not given. The reflector never
                builds a default cache: where a cache is written is the
                caller's decision.
        """
        if repository is None:
            raise ValueError(
                "Reflector requires an explicit repository; pass "
                "InMemoryReflectionRepository(), JsonReflectionRepository(directory), "
                "or another ReflectionRepository"
            )
        self._source = source
        self._repository = repository

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

        An empty ``names`` falls back to the selection of the source, and then
        to every table of the schema.

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
            table_names: Tables the session may reflect; the selection of the
                source when empty.
            force: Clear the cached entry when the session starts.

        Returns:
            A session that reflects on demand and caches on close.
        """
        return ReflectionSession(
            self._source,
            repository=self._repository,
            catalog=catalog,
            schema=schema,
            table_names=table_names or self._source.table_names,
            force=force,
        )


__all__ = ["Reflector"]
