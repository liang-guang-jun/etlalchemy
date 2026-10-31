"""Inspect a live database and cache the reflected metadata.

The :class:`LiveInspector` wraps SQLAlchemy's ``Inspector`` so every dialect is
handled by SQLAlchemy instead of by dialect-specific ``information_schema``
queries. :class:`ReflectionSession` sits on top: it loads a cached entry,
reflects the tables a call asks for, and saves the cache when it closes.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, cast

import sqlalchemy as sa

from etlalchemy.reflect.databricks import databricks_connection
from etlalchemy.reflect.source import ReflectSource
from etlalchemy.reflect.table import ReflectedColumn, ReflectedTable

if TYPE_CHECKING:
    from etlalchemy.reflect.reflector import Reflector
    from etlalchemy.reflect.repositories import ReflectionRepository


class LiveInspector:
    """Read table metadata through the SQLAlchemy inspector."""

    def __init__(
        self,
        connection_url: str,
        connect_args: dict[str, object] | None = None,
    ) -> None:
        """Create the engine and the inspector for one connection."""
        self._engine = sa.create_engine(connection_url, connect_args=connect_args or {})
        self._inspector = sa.inspect(self._engine)

    def table_names(self, schema: str | None) -> tuple[str, ...]:
        """Return the sorted table names of a schema."""
        names = self._inspector.get_table_names(schema=schema)
        return tuple(sorted(names))

    def table(self, name: str, schema: str | None) -> ReflectedTable:
        """Return the reflected columns and primary key of one table."""
        columns = tuple(
            ReflectedColumn(
                name=column["name"],
                sa_type=cast(Any, column.get("type")),
                nullable=bool(column.get("nullable", True)),
            )
            for column in self._inspector.get_columns(name, schema=schema)
        )
        constraint = self._inspector.get_pk_constraint(name, schema=schema)
        primary_key = tuple(constraint.get("constrained_columns") or ())
        return ReflectedTable(
            name=name,
            columns=columns,
            primary_key=primary_key,
            sqlalchemy_table=self._sqlalchemy_table(name, schema),
        )

    def close(self) -> None:
        """Dispose the engine behind the inspector."""
        self._engine.dispose()

    def __enter__(self) -> LiveInspector:
        """Return the inspector itself."""
        return self

    def __exit__(self, *exc_info: object) -> None:
        """Close the engine when leaving a ``with`` block."""
        self.close()

    def _sqlalchemy_table(self, name: str, schema: str | None) -> sa.Table | None:
        """Return the live ``Table`` of a reflected table, if it loads."""
        try:
            return sa.Table(
                name,
                sa.MetaData(),
                autoload_with=self._engine,
                schema=schema,
            )
        except sa.exc.SQLAlchemyError:
            return None


class ReflectionSession:
    """Reflect tables of one source on demand, backed by a repository.

    Building a session does not connect to the database. The live inspector is
    created the first time a table or a table name is needed. Reflected tables
    are written to the repository when the session closes and at least one
    table changed.

    ``inspector_factory`` replaces the live inspector, and is called with the
    source instead of resolving a connection URL. ``schema_argument`` replaces
    the default ``catalog.schema`` schema argument; both receive the source
    metadata the session was built with.
    """

    def __init__(
        self,
        source: ReflectSource,
        *,
        repository: ReflectionRepository,
        catalog: str | None = None,
        schema: str | None = None,
        table_names: tuple[str, ...] = (),
        force: bool = False,
        inspector_factory: Callable[[ReflectSource], Any] | None = None,
        schema_argument: Callable[[str | None, str | None], str | None] | None = None,
    ) -> None:
        """Keep the source, the selection and the repository, without connecting."""
        self._source = source
        self._repository = repository
        self._catalog = catalog
        self._schema = schema
        self._selection = tuple(sorted(set(table_names)))
        self._force = force
        self._tables: dict[str, ReflectedTable] = {}
        self._complete = False
        self._dirty = False
        self._loaded = False
        self._connection: tuple[str, dict[str, object]] | None = None
        self._inspector: LiveInspector | None = None
        self._inspector_factory = inspector_factory
        self._schema_argument = schema_argument

    @property
    def table_names(self) -> tuple[str, ...]:
        """Return the tables of the source, from the cache or the database."""
        if self._selection:
            return self._selection
        self._load()
        if self._complete:
            return tuple(sorted(self._tables))
        return self._live().table_names(self._effective_schema())

    def table(self, name: str) -> ReflectedTable:
        """Return one table, reflecting it when it is not cached yet.

        Raises:
            ValueError: If the session selects its tables and does not list
                ``name``.
        """
        self._load()
        cached = self._tables.get(name)
        if cached is not None:
            return cached
        if self._selection and name not in self._selection:
            raise ValueError(f"Table {name!r} is not part of the reflected selection")
        reflected = self._live().table(name, self._effective_schema())
        self._tables[name] = reflected
        self._dirty = True
        self._complete = self._complete or self._selection_complete()
        return reflected

    def tables(self) -> tuple[ReflectedTable, ...]:
        """Return every table of the source, sorted by name."""
        self._load()
        if not self._complete:
            for name in self.table_names:
                self.table(name)
            self._complete = True
            self._dirty = True
        return tuple(self._tables[name] for name in sorted(self._tables))

    def close(self) -> None:
        """Save the reflected tables and dispose the live inspector."""
        if self._dirty and self._tables:
            self._repository.save(
                self._cache_key(),
                tuple(self._tables[name] for name in sorted(self._tables)),
                complete=self._complete,
            )
            self._dirty = False
        if self._inspector is not None:
            self._inspector.close()
            self._inspector = None

    def __enter__(self) -> ReflectionSession:
        """Return the session itself."""
        return self

    def __exit__(self, *exc_info: object) -> None:
        """Save and close when leaving a ``with`` block."""
        self.close()

    def _load(self) -> None:
        """Load the cached entry once, or clear it when forcing."""
        if self._loaded:
            return
        self._loaded = True
        key = self._cache_key()
        if self._force:
            self._repository.clear(key)
            return
        entry = self._repository.get_entry(key)
        if entry is None:
            return
        cached, complete = entry
        self._tables = {table.name: table for table in cached}
        self._complete = complete

    def _selection_complete(self) -> bool:
        """Return whether every selected table has been reflected."""
        if not self._selection:
            return False
        return all(name in self._tables for name in self._selection)

    def _effective_schema(self) -> str | None:
        """Return the schema argument to pass to the SQLAlchemy inspector."""
        if self._schema_argument is not None:
            return self._schema_argument(self._catalog, self._schema)
        if self._is_databricks_source():
            return self._schema
        if self._catalog and self._schema:
            return f"{self._catalog}.{self._schema}"
        return self._catalog or self._schema

    def _is_databricks_source(self) -> bool:
        """Return whether the source connects through the Databricks dialect.

        A custom inspector never resolves the connection URL, so it is never
        treated as a Databricks source.
        """
        if self._inspector_factory is not None:
            return False
        url = sa.engine.make_url(self._connection_details()[0])
        return url.get_backend_name() == "databricks"

    def _connection_details(self) -> tuple[str, dict[str, object]]:
        """Resolve and cache the connection URL and its connect args."""
        if self._connection is None:
            self._connection = databricks_connection(self._source)
        return self._connection

    def _live(self) -> LiveInspector:
        """Create the live inspector on first use."""
        if self._inspector is None:
            if self._inspector_factory is not None:
                self._inspector = self._inspector_factory(self._source)
            else:
                url, connect_args = self._connection_details()
                self._inspector = LiveInspector(self._decorate_url(url), connect_args)
        return self._inspector

    def _decorate_url(self, url: str) -> str:
        """Add the catalog and the schema a Databricks URL has to carry.

        The Databricks dialect fixes the catalog when the connection opens, so
        it has to be part of the URL instead of the schema argument.
        """
        parsed = sa.engine.make_url(url)
        if parsed.get_backend_name() != "databricks":
            return url
        query = dict(parsed.query)
        if self._catalog:
            query.setdefault("catalog", self._catalog)
        if self._schema:
            query.setdefault("schema", self._schema)
        # ``str(url)`` masks the password, which would drop the access token.
        return parsed.set(query=query).render_as_string(hide_password=False)

    def _connection_identity(self) -> str:
        """Return what identifies the connection behind this session.

        A custom inspector never resolves a connection URL, so it stands for its
        own connection and is identified by the factory. Factories defined in
        the same scope therefore share a cache entry.
        """
        if self._inspector_factory is not None:
            factory = self._inspector_factory
            name = getattr(
                factory,
                "__qualname__",
                type(factory).__qualname__,
            )
            return f"factory:{name}"
        url = sa.engine.make_url(self._connection_details()[0])
        return str(url.host or url.database)

    def _cache_key(self) -> str:
        """Return a stable key for the connection, schema and table selection."""
        parts = "|".join(
            (
                self._connection_identity(),
                self._catalog or "",
                self._schema or "",
                ",".join(self._selection),
            )
        )
        return hashlib.sha256(parts.encode()).hexdigest()[:16]


def reflect_tables(
    source: ReflectSource,
    *,
    catalog: str | None = None,
    schema: str | None = None,
    table_names: tuple[str, ...] = (),
    force: bool = False,
    repository: ReflectionRepository | None = None,
    reflector: Reflector | None = None,
) -> tuple[ReflectedTable, ...]:
    """Reflect tables of a source once.

    This is the one-shot convenience function: it builds a
    :class:`~etlalchemy.reflect.reflector.Reflector` around the source and
    reflects either the named tables or every table of the schema. Use a
    ``Reflector`` when several calls share one repository.

    Args:
        source: Database to reflect.
        catalog: Optional catalog passed to the inspector.
        schema: Optional schema passed to the inspector.
        table_names: Tables to reflect; an empty tuple reflects every table of
            the schema.
        force: Clear the cached entry before reflecting.
        repository: Cache to use; the default in-memory cache when ``None``.
        reflector: Ready-made reflector; one is built from ``repository`` when
            ``None``.

    Returns:
        The reflected tables, sorted by name.
    """
    from etlalchemy.reflect.reflector import Reflector

    active = reflector or Reflector(source, repository)
    if table_names:
        return active.tables(
            table_names,
            catalog=catalog,
            schema=schema,
            force=force,
        )
    return active.all_tables(catalog=catalog, schema=schema, force=force)


__all__ = ["LiveInspector", "ReflectionSession", "reflect_tables"]
