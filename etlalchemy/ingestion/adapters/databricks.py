"""Databricks data source adapter and type mapper."""

from __future__ import annotations

import asyncio
import importlib
import re
from typing import TYPE_CHECKING, Any, Literal

from etlalchemy.catalog.aggregates.types import DataType
from etlalchemy.ingestion.adapters._options import type_policy
from etlalchemy.ingestion.adapters.databricks_profiles import read_profiles
from etlalchemy.ingestion.aggregates.errors import MissingCredentialError, UnsupportedTypeError
from etlalchemy.ingestion.ports.data_source import ColumnInfo, DataSourcePort, SourceProfile
from etlalchemy.shared.credentials import profile_reference

if TYPE_CHECKING:
    from etlalchemy.ingestion.aggregates.connection import SourceConnection
    from etlalchemy.ingestion.ports.secrets import SecretValue

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
    port itself stays asynchronous like every other source kind.
    """

    def __init__(self, client: Any, type_mapper: DatabricksTypeMapper) -> None:
        """Wraps an already configured ``WorkspaceClient``."""
        self._client: Any = client
        self._types = type_mapper

    async def list_catalogs(self) -> list[str]:
        """Returns the catalog names visible to the client."""
        catalogs = await asyncio.to_thread(self._client.catalogs.list)
        return [catalog.name for catalog in catalogs if catalog.name]

    async def list_schemas(self, catalog: str) -> list[str]:
        """Returns the schema names of a catalog."""
        schemas = await asyncio.to_thread(
            self._client.schemas.list,
            catalog_name=catalog,
        )
        return [schema.name for schema in schemas if schema.name]

    async def list_tables(self, catalog: str, schema: str) -> list[str]:
        """Returns the table names of a schema."""
        tables = await asyncio.to_thread(
            self._client.tables.list,
            catalog_name=catalog,
            schema_name=schema,
        )
        return [table.name for table in tables if table.name]

    async def list_columns(self, catalog: str, schema: str, table: str) -> list[ColumnInfo]:
        """Returns the columns of a table as native type strings."""
        info = await asyncio.to_thread(
            self._client.tables.get,
            f"{catalog}.{schema}.{table}",
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
        """Drops the underlying client."""
        self._client = None


class DatabricksSourceFactory:
    """Builds :class:`DatabricksSource` instances for ``kind == "databricks"``."""

    kind = "databricks"
    """The ``SourceConnection.kind`` this factory handles."""
    profile_capable = True
    """A Databricks connection may authenticate through a local CLI profile."""

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
        client_class = _workspace_client_class()
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
        client = await asyncio.to_thread(client_class, **kwargs)
        return DatabricksSource(client, self.type_mapper(connection))

    async def list_profiles(self) -> list[SourceProfile]:
        """Returns the Databricks CLI profiles configured on this machine."""
        return await asyncio.to_thread(read_profiles)

    def type_mapper(self, connection: SourceConnection) -> DatabricksTypeMapper:
        """Returns the type mapper configured by the connection options."""
        return DatabricksTypeMapper(on_unsupported=type_policy(connection))


def _workspace_client_class() -> Any:
    """Imports the Databricks SDK lazily so it stays an optional dependency."""
    module = importlib.import_module("databricks.sdk")
    return module.WorkspaceClient
