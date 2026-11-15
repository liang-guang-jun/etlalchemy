"""Protocols that isolate the ingestion context from concrete sources."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from etlalchemy.catalog.aggregates.types import DataType
    from etlalchemy.ingestion.aggregates.connection import SourceConnection
    from etlalchemy.ingestion.ports.secrets import SecretValue


@dataclass(frozen=True)
class ColumnInfo:
    """One column as reported by a data source, in native form."""

    name: str
    """Column name."""
    raw_type: str
    """Native type, for example ``DECIMAL(10,2)`` or ``ARRAY<STRING>``."""
    nullable: bool
    """Whether the source reports the column as nullable."""


@dataclass(frozen=True)
class SourceProfile:
    """One local credential profile a source can authenticate with."""

    name: str
    """Profile name as stored by the tool that owns it."""
    host: str | None = None
    """Endpoint stored in the profile, when it records one."""


class ColumnTypeMapper(Protocol):
    """Maps native source types onto the catalog data type vocabulary."""

    def map(self, raw_type: str) -> DataType | None:
        """Returns the catalog type, or ``None`` when the type is skipped."""
        ...


class DataSourcePort(Protocol):
    """Read-only view of a data source; one instance per import."""

    async def list_catalogs(self) -> list[str]:
        """Returns the top-level containers of the source."""
        ...

    async def list_schemas(self, catalog: str) -> list[str]:
        """Returns the schemas of a source catalog."""
        ...

    async def list_tables(self, catalog: str, schema: str) -> list[str]:
        """Returns the tables of a source schema."""
        ...

    async def list_columns(
        self,
        catalog: str,
        schema: str,
        table: str,
    ) -> list[ColumnInfo]:
        """Returns the columns of a source table."""
        ...

    async def close(self) -> None:
        """Releases the client resources."""
        ...


class DataSourceFactory(Protocol):
    """Builds a :class:`DataSourcePort` and its type mapper for one connection."""

    kind: str
    """The ``SourceConnection.kind`` this factory handles."""
    profile_capable: bool
    """Whether the kind accepts a ``profile:`` credential reference."""

    async def build(
        self,
        connection: SourceConnection,
        secret: SecretValue | None,
    ) -> DataSourcePort:
        """Builds a source client for ``connection``.

        ``secret`` is ``None`` when the connection authenticates through a local
        profile instead of a stored credential.
        """
        ...

    async def list_profiles(self) -> list[SourceProfile]:
        """Returns the local profiles of the kind, or an empty list."""
        ...

    def type_mapper(self, connection: SourceConnection) -> ColumnTypeMapper:
        """Returns the type mapper configured for ``connection``."""
        ...
