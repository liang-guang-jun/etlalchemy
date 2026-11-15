"""Fakes shared by the ingestion context tests."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from etlalchemy.catalog.aggregates.types import DataType
from etlalchemy.catalog.application import CatalogApplication
from etlalchemy.catalog.projection.view import FieldRow
from etlalchemy.ingestion.aggregates.errors import UnsupportedTypeError
from etlalchemy.ingestion.ports.data_source import ColumnInfo, DataSourcePort, SourceProfile
from etlalchemy.ingestion.ports.secrets import SecretValue


class FakeCatalogView:
    """Catalog view that returns the ids created during a test."""

    def __init__(self) -> None:
        self.schema_ids: dict[tuple[UUID, str], UUID] = {}
        self.table_ids: dict[tuple[UUID, str], UUID] = {}
        self.application: CatalogApplication | None = None

    async def find_schema_id(self, catalog_id: UUID, name: str) -> UUID | None:
        """Returns the id recorded for a schema name."""
        return self.schema_ids.get((catalog_id, name))

    async def find_table_id(self, schema_id: UUID, name: str) -> UUID | None:
        """Returns the id recorded for a table name."""
        return self.table_ids.get((schema_id, name))

    async def list_fields(self, table_id: UUID) -> list[FieldRow]:
        """Returns the fields of a table from the backing catalog application."""
        if self.application is None:
            return []
        table = await self.application.repository.get(table_id)
        return [
            FieldRow(
                table_id=table.id,
                field_id=field.field_id,
                name=field.name,
                data_type=field.data_type,
                nullable=field.nullable,
                comment=field.comment,
            )
            for field in table.fields.values()
        ]


class RecordingCatalogApplication(CatalogApplication):
    """Catalog application that mirrors created children into a fake view."""

    def __init__(self, view: FakeCatalogView, env: dict[str, str] | None = None) -> None:
        """Stores the fake view updated on child creation."""
        super().__init__(env=env)
        self.view = view
        view.application = self

    async def create_schema(
        self,
        catalog_id: UUID,
        schema_name: str,
        description: str = "",
    ) -> UUID:
        """Creates the schema and records its id in the fake view."""
        schema_id = await super().create_schema(catalog_id, schema_name, description)
        self.view.schema_ids[(catalog_id, schema_name)] = schema_id
        return schema_id

    async def add_table(self, catalog_id: UUID, schema: UUID | str, table_name: str) -> UUID:
        """Creates the table and records its id in the fake view."""
        table_id = await super().add_table(catalog_id, schema, table_name)
        loaded = await self.get_schema(catalog_id, schema)
        self.view.table_ids[(loaded.id, table_name)] = table_id
        return table_id


class FakeConnectionsView:
    """Minimal stand-in for the ingestion connection read model."""

    def __init__(self) -> None:
        self.by_name: dict[str, UUID] = {}

    async def find_connection_by_name(self, name: str) -> Any | None:
        """Returns a row-like object when the name is registered."""
        connection_id = self.by_name.get(name)
        if connection_id is None:
            return None
        return {"connection_id": connection_id, "name": name}


class FakeTypeMapper:
    """Maps native type names through the catalog vocabulary."""

    def map(self, raw_type: str) -> DataType | None:
        """Returns ``None`` for the ``skip`` marker, else the parsed type."""
        if raw_type == "skip":
            return None
        if raw_type == "unsupported":
            raise UnsupportedTypeError(raw_type)
        return DataType.parse(raw_type)


@dataclass
class FakeSource:
    """In-memory source tree used by the application tests."""

    catalogs: dict[str, dict[str, dict[str, list[ColumnInfo]]]] = field(default_factory=dict)
    fail_with: str | None = None
    closed: bool = False

    async def list_catalogs(self) -> list[str]:
        """Returns the configured catalog names, or raises when configured."""
        if self.fail_with is not None:
            raise RuntimeError(self.fail_with)
        return list(self.catalogs)

    async def list_schemas(self, catalog: str) -> list[str]:
        """Returns the schemas of a catalog, or raises when configured."""
        if self.fail_with is not None:
            raise RuntimeError(self.fail_with)
        return list(self.catalogs.get(catalog, {}))

    async def list_tables(self, catalog: str, schema: str) -> list[str]:
        """Returns the tables of a schema."""
        return list(self.catalogs.get(catalog, {}).get(schema, {}))

    async def list_columns(self, catalog: str, schema: str, table: str) -> list[ColumnInfo]:
        """Returns the columns of a table."""
        return list(self.catalogs.get(catalog, {}).get(schema, {}).get(table, []))

    async def close(self) -> None:
        """Marks the source as closed."""
        self.closed = True


class FakeSourceFactory:
    """Builds a shared fake source and records the resolved secret."""

    kind = "fake"
    profile_capable = True

    def __init__(self, source: FakeSource) -> None:
        self.source = source
        self.secrets: list[str | None] = []

    async def build(
        self,
        connection: Any,
        secret: SecretValue | None,
    ) -> DataSourcePort:
        """Records the secret (``None`` for a profile) and returns the source."""
        self.secrets.append(None if secret is None else secret.value)
        return self.source

    async def list_profiles(self) -> list[SourceProfile]:
        """Returns one deterministic local profile."""
        return [SourceProfile(name="fake", host="https://fake.test")]

    def type_mapper(self, connection: Any) -> FakeTypeMapper:
        """Returns the fake type mapper."""
        return FakeTypeMapper()
