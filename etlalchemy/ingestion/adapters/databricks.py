"""Databricks data source adapter and type mapper.

The ``databricks-sdk`` client is synchronous and its list endpoints answer with
lazy iterators, so every call runs inside a worker thread and its paging is
consumed there as well: iterating a list on the event loop would block the rest
of the service while the pages arrive.

Building the client is the expensive part (configuration resolution and the
first OAuth exchange of a CLI profile), and Unity Catalog returns whole table
definitions unless it is asked not to, so the factory keeps a short-lived client
cache and every level asks for the smallest payload it needs.
"""

from __future__ import annotations

import asyncio
import hashlib
import importlib
import inspect
import re
import time
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any, Literal

import structlog

from etlalchemy.catalog.aggregates.types import DataType
from etlalchemy.ingestion.adapters._options import int_option, type_policy
from etlalchemy.ingestion.adapters.databricks_profiles import read_profiles
from etlalchemy.ingestion.aggregates.errors import MissingCredentialError, UnsupportedTypeError
from etlalchemy.ingestion.ports.data_source import ColumnInfo, DataSourcePort, SourceProfile
from etlalchemy.shared.credentials import profile_reference
from etlalchemy.shared.logging import get_logger

if TYPE_CHECKING:
    from etlalchemy.ingestion.aggregates.connection import SourceConnection
    from etlalchemy.ingestion.ports.secrets import SecretValue

_LOGGER_NAME = "ingestion.adapters.databricks"
_DEFAULT_PAGE_SIZE = 200
_DEFAULT_CLIENT_TTL_SECONDS = 900
_DEFAULT_METADATA_TTL_SECONDS = 30
_MAX_CACHED_CLIENTS = 8
_MAX_CACHED_LEVELS = 128
_TIMEOUT_OPTIONS = ("http_timeout_seconds", "retry_timeout_seconds")

_SIMPLE_TYPES: dict[str, str] = {
    "STRING": "string",
    "TEXT": "text",
    "INT": "integer",
    "INTEGER": "integer",
    "BIGINT": "bigint",
    "SMALLINT": "smallint",
    "TINYINT": "smallint",
    "DOUBLE": "double",
    "FLOAT": "float",
    "REAL": "float",
    "BOOLEAN": "boolean",
    "DATE": "date",
    "TIMESTAMP": "timestamp",
    "TIMESTAMP_NTZ": "timestamp",
    "BINARY": "binary",
    "VARCHAR": "varchar",
    "CHAR": "char",
    "DECIMAL": "decimal",
    "NUMERIC": "decimal",
}

_PARAMETERIZED_RE = re.compile(r"^(DECIMAL|NUMERIC|VARCHAR|CHAR)\((\d+)(?:,(\d+))?\)$")


class _ExpiringCache[K, V]:
    """Small first-in-first-out map whose entries expire after a per-entry TTL."""

    def __init__(
        self,
        clock: Callable[[], float],
        maxsize: int,
        on_evict: Callable[[V], None] | None = None,
    ) -> None:
        """Stores the clock, the size limit and the eviction callback."""
        self._clock = clock
        self._maxsize = maxsize
        self._on_evict = on_evict
        self._entries: dict[K, tuple[float, V]] = {}

    def get(self, key: K) -> V | None:
        """Returns a live entry and drops it once it has expired."""
        entry = self._entries.get(key)
        if entry is None:
            return None
        expires_at, value = entry
        if expires_at <= self._clock():
            del self._entries[key]
            self._evict(value)
            return None
        return value

    def put(self, key: K, value: V, ttl: float) -> None:
        """Stores an entry; a non-positive TTL disables caching entirely."""
        if ttl <= 0:
            return
        self._entries[key] = (self._clock() + ttl, value)
        while len(self._entries) > self._maxsize:
            oldest = next(iter(self._entries))
            _, evicted = self._entries.pop(oldest)
            self._evict(evicted)

    def _evict(self, value: V) -> None:
        """Runs the eviction callback of the cache when it has one."""
        if self._on_evict is not None:
            self._on_evict(value)


def _elapsed_ms(started: float) -> int:
    """Returns the milliseconds elapsed since ``started``."""
    return int((time.monotonic() - started) * 1000)


def _accepted_kwargs(method: Callable[..., Any], kwargs: dict[str, Any]) -> dict[str, Any]:
    """Drops keyword arguments the installed SDK version does not accept."""
    try:
        parameters = inspect.signature(method).parameters
    except (TypeError, ValueError):
        return kwargs
    if any(parameter.kind is inspect.Parameter.VAR_KEYWORD for parameter in parameters.values()):
        return kwargs
    return {name: value for name, value in kwargs.items() if name in parameters}


def _consume(method: Callable[..., Any], kwargs: dict[str, Any]) -> list[Any]:
    """Runs an SDK list endpoint and consumes its lazy paging in the thread."""
    return list(method(**kwargs))


def _close_client(client: Any) -> None:
    """Closes the HTTP session of an SDK client and never raises."""
    close = getattr(getattr(client, "api_client", None), "close", None)
    if not callable(close):
        return
    try:
        close()
    except Exception:
        get_logger(_LOGGER_NAME).debug("databricks.client.close failed")


class DatabricksTypeMapper:
    """Maps Databricks native types onto the catalog ``DataType`` vocabulary."""

    def __init__(self, on_unsupported: Literal["fail", "json", "skip"] = "fail") -> None:
        """Stores the policy applied to types outside the catalog vocabulary."""
        self.on_unsupported = on_unsupported

    def map(self, raw: str) -> DataType | None:
        """Returns the catalog type, or ``None`` when the policy is ``skip``."""
        text = raw.strip().upper()
        if text in _SIMPLE_TYPES:
            return DataType.parse(_SIMPLE_TYPES[text])
        match = _PARAMETERIZED_RE.match(text)
        if match is not None:
            base = match.group(1)
            first = match.group(2)
            second = match.group(3)
            if base in ("DECIMAL", "NUMERIC"):
                return DataType.parse(f"decimal({first},{second or '0'})")
            return DataType.parse(f"{base.lower()}({first})")
        if self.on_unsupported == "json":
            return DataType.parse("json")
        if self.on_unsupported == "skip":
            return None
        msg = f"Unsupported Databricks type: {raw!r}"
        raise UnsupportedTypeError(msg)


class DatabricksSource:
    """Read-only Databricks source backed by ``databricks-sdk``.

    The SDK is synchronous, so every call is dispatched to a worker thread; the
    port itself stays asynchronous like every other source kind. Level reads are
    served from the factory cache when it is enabled, and each list endpoint is
    asked for the smallest payload its level needs.
    """

    def __init__(
        self,
        client: Any,
        type_mapper: DatabricksTypeMapper,
        *,
        source_key: str = "",
        levels: _ExpiringCache[tuple[Any, ...], list[str]] | None = None,
        metadata_ttl: int = 0,
        page_size: int = _DEFAULT_PAGE_SIZE,
        owns_client: bool = True,
    ) -> None:
        """Wraps an already configured ``WorkspaceClient`` and its level cache."""
        self._client: Any = client
        self._types = type_mapper
        self._source_key = source_key
        self._levels = levels
        self._metadata_ttl = metadata_ttl
        self._page_size = page_size
        self._owns_client = owns_client
        self._log: structlog.stdlib.BoundLogger = get_logger(_LOGGER_NAME)

    async def list_catalogs(self) -> list[str]:
        """Returns the catalog names visible to the client."""
        return await self._level(
            ("catalogs",),
            lambda: self._list_call("catalogs.list", self._client.catalogs.list),
        )

    async def list_schemas(self, catalog: str) -> list[str]:
        """Returns the schema names of a catalog."""
        return await self._level(
            ("schemas", catalog),
            lambda: self._list_call(
                "schemas.list",
                self._client.schemas.list,
                catalog_name=catalog,
                max_results=self._page_size,
            ),
        )

    async def list_tables(self, catalog: str, schema: str) -> list[str]:
        """Returns the table names of a schema without their column metadata."""
        return await self._level(
            ("tables", catalog, schema),
            lambda: self._list_call(
                "tables.list",
                self._client.tables.list,
                catalog_name=catalog,
                schema_name=schema,
                omit_columns=True,
                omit_properties=True,
                max_results=self._page_size,
            ),
        )

    async def list_columns(self, catalog: str, schema: str, table: str) -> list[ColumnInfo]:
        """Returns the columns of a table as native type strings."""
        info = await self._one_call(
            "tables.get",
            self._client.tables.get,
            full_name=f"{catalog}.{schema}.{table}",
        )
        columns = getattr(info, "columns", None) or []
        return [
            ColumnInfo(
                name=column.name,
                raw_type=str(column.type_text or column.type_name or "STRING"),
                nullable=bool(column.nullable),
            )
            for column in columns
        ]

    async def close(self) -> None:
        """Releases the client unless the factory shares it between sources."""
        if not self._owns_client:
            return
        client, self._client = self._client, None
        if client is not None:
            await asyncio.to_thread(_close_client, client)

    async def _level(
        self,
        path: tuple[Any, ...],
        load: Callable[[], Awaitable[list[Any]]],
    ) -> list[str]:
        """Returns one level of the source tree as names, cached when possible."""
        key = (self._source_key, *path)
        cached = self._levels.get(key) if self._levels is not None else None
        if cached is not None:
            self._log.debug("databricks.level", level=path[0], items=len(cached), cache="hit")
            return list(cached)
        names = [row.name for row in await load() if row.name]
        if self._levels is not None and self._metadata_ttl > 0:
            self._levels.put(key, names, float(self._metadata_ttl))
        self._log.debug("databricks.level", level=path[0], items=len(names), cache="miss")
        return names

    async def _list_call(
        self,
        operation: str,
        method: Callable[..., Any],
        /,
        **kwargs: Any,
    ) -> list[Any]:
        """Runs one SDK list endpoint in a worker thread, paging included."""
        accepted = _accepted_kwargs(method, kwargs)
        started = time.monotonic()
        try:
            rows = await asyncio.to_thread(_consume, method, accepted)
        except Exception:
            self._log.exception(
                "databricks.call failed",
                operation=operation,
                duration_ms=_elapsed_ms(started),
            )
            raise
        self._log.debug(
            "databricks.call",
            operation=operation,
            items=len(rows),
            duration_ms=_elapsed_ms(started),
        )
        return rows

    async def _one_call(
        self,
        operation: str,
        method: Callable[..., Any],
        /,
        **kwargs: Any,
    ) -> Any:
        """Runs one SDK call in a worker thread and returns its object."""
        accepted = _accepted_kwargs(method, kwargs)
        started = time.monotonic()
        try:
            result: Any = await asyncio.to_thread(lambda: method(**accepted))
        except Exception:
            self._log.exception(
                "databricks.call failed",
                operation=operation,
                duration_ms=_elapsed_ms(started),
            )
            raise
        self._log.debug(
            "databricks.call",
            operation=operation,
            duration_ms=_elapsed_ms(started),
        )
        return result


class DatabricksSourceFactory:
    """Builds :class:`DatabricksSource` instances for ``kind == "databricks"``.

    The factory outlives a single request, so it owns the two caches that make
    browsing a source affordable: one client per endpoint and credential (so a
    tree expansion does not pay the authentication handshake again) and one
    short-lived entry per inspected level.
    """

    kind = "databricks"
    """The ``SourceConnection.kind`` this factory handles."""
    profile_capable = True
    """A Databricks connection may authenticate through a local CLI profile."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        """Creates the client and level caches shared by every source."""
        self._clients: _ExpiringCache[str, Any] = _ExpiringCache(
            clock,
            _MAX_CACHED_CLIENTS,
            _close_client,
        )
        self._levels: _ExpiringCache[tuple[Any, ...], list[str]] = _ExpiringCache(
            clock,
            _MAX_CACHED_LEVELS,
        )
        self._log: structlog.stdlib.BoundLogger = get_logger(_LOGGER_NAME)

    async def build(
        self,
        connection: SourceConnection,
        secret: SecretValue | None,
    ) -> DataSourcePort:
        """Builds a Databricks client for ``connection``.

        A ``profile:`` credential reference reads the workspace host and the
        credentials from the local Databricks CLI configuration, so ``secret``
        may be ``None``. An explicit endpoint overrides the profile host.
        """
        profile = profile_reference(connection.credential_ref)
        kwargs = self._client_kwargs(connection, profile, secret)
        source_key = _source_key(connection, profile, secret)
        client_ttl = int_option(
            connection,
            "client_cache_ttl_seconds",
            _DEFAULT_CLIENT_TTL_SECONDS,
        )
        client = self._clients.get(source_key) if client_ttl > 0 else None
        shared = client is not None
        if client is None:
            client = await self._connect(connection, kwargs)
            if client_ttl > 0:
                cached = self._clients.get(source_key)
                if cached is None:
                    # The cache owns the client from here on; the source only
                    # borrows it, so ``close()`` must not tear it down.
                    self._clients.put(source_key, client, float(client_ttl))
                    shared = True
                else:
                    # Another request won the race; keep the cached client and
                    # release the one this call just built.
                    await asyncio.to_thread(_close_client, client)
                    client = cached
                    shared = True
        page_size = int_option(connection, "page_size", _DEFAULT_PAGE_SIZE)
        return DatabricksSource(
            client,
            self.type_mapper(connection),
            source_key=source_key,
            levels=self._levels,
            metadata_ttl=int_option(
                connection,
                "metadata_cache_ttl",
                _DEFAULT_METADATA_TTL_SECONDS,
            ),
            page_size=page_size if page_size > 0 else _DEFAULT_PAGE_SIZE,
            owns_client=not shared,
        )

    async def list_profiles(self) -> list[SourceProfile]:
        """Returns the Databricks CLI profiles configured on this machine."""
        return await asyncio.to_thread(read_profiles)

    def type_mapper(self, connection: SourceConnection) -> DatabricksTypeMapper:
        """Returns the type mapper configured by the connection options."""
        return DatabricksTypeMapper(on_unsupported=type_policy(connection))

    async def _connect(
        self,
        connection: SourceConnection,
        kwargs: dict[str, Any],
    ) -> Any:
        """Builds the SDK client, dropping timeout options an older SDK rejects."""
        client_class = _workspace_client_class()
        accepted = _accepted_kwargs(client_class, kwargs)
        started = time.monotonic()
        try:
            client = await asyncio.to_thread(lambda: client_class(**accepted))
        except TypeError:
            fallback = {
                name: value for name, value in accepted.items() if name not in _TIMEOUT_OPTIONS
            }
            if fallback == accepted:
                raise
            self._log.warning(
                "databricks.client.options unsupported",
                connection_id=str(connection.id),
            )
            client = await asyncio.to_thread(lambda: client_class(**fallback))
        self._log.info(
            "databricks.client.created",
            connection_id=str(connection.id),
            host=connection.endpoint,
            credential="profile" if profile_reference(connection.credential_ref) else "inline",
            duration_ms=_elapsed_ms(started),
        )
        return client

    @staticmethod
    def _client_kwargs(
        connection: SourceConnection,
        profile: str | None,
        secret: SecretValue | None,
    ) -> dict[str, Any]:
        """Returns the ``WorkspaceClient`` keyword arguments of a connection."""
        kwargs: dict[str, Any] = {}
        if profile is not None:
            kwargs["profile"] = profile or None
            if connection.endpoint.strip():
                kwargs["host"] = connection.endpoint
        else:
            if secret is None:
                raise MissingCredentialError(str(connection.id))
            kwargs["host"] = connection.endpoint
            kwargs["token"] = secret.value
        for name in _TIMEOUT_OPTIONS:
            seconds = int_option(connection, name, 0)
            if seconds > 0:
                kwargs[name] = seconds
        return kwargs


def _source_key(
    connection: SourceConnection,
    profile: str | None,
    secret: SecretValue | None,
) -> str:
    """Returns the cache key of the client a connection would build.

    The key carries a digest of the token rather than the token itself, so a
    rotated credential opens a new client and the old one expires on its own.
    """
    host = connection.endpoint.strip()
    if profile is not None:
        return f"profile:{profile}@{host}"
    token = "" if secret is None else secret.value
    return f"token:{hashlib.sha256(token.encode()).hexdigest()}@{host}"


def _workspace_client_class() -> Any:
    """Imports the Databricks SDK lazily so it stays an optional dependency."""
    module = importlib.import_module("databricks.sdk")
    return module.WorkspaceClient
