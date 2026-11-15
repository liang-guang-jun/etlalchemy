"""Read-only PostgreSQL data source adapter and type mapper."""

from __future__ import annotations

import importlib
import re
from typing import TYPE_CHECKING, Any, Literal
from urllib.parse import urlsplit

from etlalchemy.catalog.aggregates.types import DataType
from etlalchemy.ingestion.adapters._options import (
    bool_option,
    int_option,
    json_option,
    type_policy,
)
from etlalchemy.ingestion.aggregates.errors import (
    IngestionError,
    UnknownCatalogError,
    UnsupportedTypeError,
)
from etlalchemy.ingestion.ports.data_source import ColumnInfo, DataSourcePort, SourceProfile

if TYPE_CHECKING:
    from etlalchemy.ingestion.aggregates.connection import SourceConnection
    from etlalchemy.ingestion.ports.secrets import SecretValue

_SIMPLE: dict[str, str] = {
    "boolean": "boolean",
    "smallint": "smallint",
    "int2": "smallint",
    "integer": "integer",
    "int": "integer",
    "int4": "integer",
    "bigint": "bigint",
    "int8": "bigint",
    "real": "float",
    "float4": "float",
    "double precision": "double",
    "float8": "double",
    "text": "text",
    "json": "json",
    "jsonb": "json",
    "bytea": "binary",
    "date": "date",
    "timestamp": "timestamp",
    "timestamp without time zone": "timestamp",
    "timestamp with time zone": "timestamp",
    "xml": "text",
    "money": "decimal(19,2)",
    "uuid": "uuid",
}

_PARAM_RE = re.compile(
    r"^(?P<base>character varying|varchar|character|char|bpchar|numeric|decimal|"
    r"bit varying|varbit|bit|timestamp|time)"
    r"(?:\((?P<p>\d+)(?:,(?P<s>\d+))?\))?"
    r"(?:\s+(?P<tz>with|without) time zone)?$"
)

_SCHEMA_SQL = """
SELECT n.nspname
FROM pg_catalog.pg_namespace n
WHERE n.nspname <> 'information_schema'
  AND n.nspname !~ '^pg_'
  AND pg_catalog.has_schema_privilege(n.oid, 'USAGE')
ORDER BY n.nspname
"""

_TABLE_SQL = """
SELECT c.relname
FROM pg_catalog.pg_class c
JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = %s
  AND c.relkind = ANY(%s)
ORDER BY c.relname
"""

_COLUMN_SQL = """
SELECT a.attname,
       pg_catalog.format_type(a.atttypid, a.atttypmod),
       NOT a.attnotnull
FROM pg_catalog.pg_attribute a
WHERE a.attrelid = (
        SELECT c.oid
        FROM pg_catalog.pg_class c
        JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = %s AND c.relname = %s
      )
  AND a.attnum > 0
  AND NOT a.attisdropped
ORDER BY a.attnum
"""


class PostgresTypeMapper:
    """Maps PostgreSQL native types onto the catalog ``DataType`` vocabulary."""

    def __init__(
        self,
        on_unsupported: Literal["fail", "json", "skip"] = "fail",
        *,
        array_as_json: bool = True,
        overrides: dict[str, str] | None = None,
    ) -> None:
        """Stores the policy, array handling and explicit type overrides."""
        self.on_unsupported = on_unsupported
        self.array_as_json = array_as_json
        self.overrides = dict(overrides or {})

    def map(self, raw: str) -> DataType | None:
        """Returns the catalog type, or ``None`` when the policy is ``skip``."""
        text = " ".join(raw.strip().lower().split())
        if text in self.overrides:
            return DataType.parse(self.overrides[text])
        if text.endswith("[]"):
            return self._array(text)
        mapped = self._scalar(text)
        if mapped is not None:
            return mapped
        return self._fallback(raw)

    def _array(self, text: str) -> DataType | None:
        """Maps an array type, either to JSON or through the policy."""
        if self.array_as_json:
            return DataType.parse("json")
        return self._fallback(text)

    def _scalar(self, text: str) -> DataType | None:
        """Maps a scalar type, or returns ``None`` when it is unsupported."""
        if text in _SIMPLE:
            return DataType.parse(_SIMPLE[text])

        match = _PARAM_RE.match(text)
        if match is None:
            return None

        base = match.group("base")
        precision = match.group("p")
        scale = match.group("s")

        if base in ("numeric", "decimal"):
            if precision is None:
                return DataType.parse("decimal")
            return DataType.parse(f"decimal({precision},{scale or '0'})")
        if base in ("character varying", "varchar"):
            return DataType.parse(f"varchar({precision})" if precision else "varchar")
        if base in ("character", "char", "bpchar"):
            return DataType.parse(f"char({precision})" if precision else "char")
        if base == "timestamp":
            return DataType.parse("timestamp")
        return None

    def _fallback(self, raw: str) -> DataType | None:
        """Applies the unsupported-type policy to an unmapped type."""
        if self.on_unsupported == "json":
            return DataType.parse("json")
        if self.on_unsupported == "skip":
            return None
        msg = f"Unsupported PostgreSQL type: {raw!r}"
        raise UnsupportedTypeError(msg)


class PostgresSource:
    """Read-only PostgreSQL source backed by an async ``psycopg`` connection."""

    def __init__(
        self,
        connection: Any,
        type_mapper: PostgresTypeMapper,
        *,
        include_views: bool = False,
    ) -> None:
        """Wraps an already configured psycopg async connection."""
        self._conn: Any = connection
        self._types = type_mapper
        kinds = ["r", "p"]
        if include_views:
            kinds += ["v", "m", "f"]
        self._relkinds = kinds

    async def list_catalogs(self) -> list[str]:
        """Returns the current database, the only catalog PostgreSQL exposes."""
        cursor = await self._conn.execute("SELECT pg_catalog.current_database()")
        row = await cursor.fetchone()
        return [row[0]] if row and row[0] else []

    async def list_schemas(self, catalog: str) -> list[str]:
        """Returns the visible, non-system schemas of the current database."""
        if catalog not in await self.list_catalogs():
            msg = f"Unknown PostgreSQL database: {catalog!r}"
            raise UnknownCatalogError(msg)
        cursor = await self._conn.execute(_SCHEMA_SQL)
        rows = await cursor.fetchall()
        return [row[0] for row in rows]

    async def list_tables(self, catalog: str, schema: str) -> list[str]:
        """Returns the tables (and optionally views) of a schema."""
        cursor = await self._conn.execute(_TABLE_SQL, (schema, self._relkinds))
        rows = await cursor.fetchall()
        return [row[0] for row in rows]

    async def list_columns(self, catalog: str, schema: str, table: str) -> list[ColumnInfo]:
        """Returns the columns of a table as ``format_type`` strings."""
        cursor = await self._conn.execute(_COLUMN_SQL, (schema, table))
        rows = await cursor.fetchall()
        return [ColumnInfo(name=row[0], raw_type=row[1], nullable=bool(row[2])) for row in rows]

    async def close(self) -> None:
        """Releases the underlying psycopg connection."""
        if self._conn is not None:
            await self._conn.close()
            self._conn = None


class PostgresSourceFactory:
    """Builds :class:`PostgresSource` instances for ``kind == "postgres"``."""

    kind = "postgres"
    """The ``SourceConnection.kind`` this factory handles."""
    profile_capable = False
    """A PostgreSQL connection always needs a stored credential."""

    async def build(
        self,
        connection: SourceConnection,
        secret: SecretValue | None,
    ) -> DataSourcePort:
        """Builds a read-only psycopg connection for ``connection``."""
        return PostgresSource(
            await _connect(connection, secret),
            self.type_mapper(connection),
            include_views=bool_option(connection, "include_views", False),
        )

    async def list_profiles(self) -> list[SourceProfile]:
        """Returns no profiles: PostgreSQL has no local profile store."""
        return []

    def type_mapper(self, connection: SourceConnection) -> PostgresTypeMapper:
        """Returns the type mapper configured by the connection options."""
        return PostgresTypeMapper(
            on_unsupported=type_policy(connection),
            array_as_json=bool_option(connection, "array_as_json", True),
            overrides=json_option(connection, "type_overrides"),
        )


def _parse_endpoint(endpoint: str) -> tuple[str, int, str | None]:
    """Parses ``host[:port]`` or ``postgresql://host[:port][/database]``."""
    text = endpoint.strip()
    if "://" in text:
        parts = urlsplit(text)
        return parts.hostname or "localhost", parts.port or 5432, parts.path.lstrip("/") or None
    host, _, port = text.rpartition(":")
    if host and port.isdigit():
        return host, int(port), None
    return text, 5432, None


async def _connect(connection: SourceConnection, secret: SecretValue | None) -> Any:
    """Opens a read-only async psycopg connection from the connection metadata."""
    if secret is None:
        msg = "a PostgreSQL connection needs a credential reference or an inline token"
        raise IngestionError(msg)
    psycopg = importlib.import_module("psycopg")
    host, port, endpoint_database = _parse_endpoint(connection.endpoint)
    database = connection.options.get("database") or connection.default_catalog or endpoint_database
    if not database:
        msg = "PostgreSQL connection requires options['database'] or default_catalog"
        raise IngestionError(msg)
    conn = await psycopg.AsyncConnection.connect(
        host=host,
        port=port,
        dbname=database,
        user=connection.options.get("user", "postgres"),
        password=secret.value,
        sslmode=connection.options.get("sslmode", "prefer"),
        connect_timeout=int_option(connection, "connect_timeout", 10),
        application_name=connection.options.get(
            "application_name",
            "etlalchemy-ingestion",
        ),
        autocommit=True,
    )
    await conn.execute("SET default_transaction_read_only = on")
    await conn.execute(
        f"SET statement_timeout = {int_option(connection, 'statement_timeout_ms', 30000)}"
    )
    return conn
