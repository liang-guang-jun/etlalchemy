"""Response models of the ingestion context."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Self
from uuid import UUID

from pydantic import BaseModel

from etlalchemy.ingestion.ports.data_source import SourceProfile
from etlalchemy.ingestion.projection.view import ConnectionRow, ImportRunRow


class ConnectionCreatedResponse(BaseModel):
    """Result of ``create_source_connection``."""

    connection_id: UUID
    """ID of the new source connection."""


class ConnectionResponse(BaseModel):
    """A source connection as exposed to delivery clients."""

    connection_id: UUID
    """ID of the connection aggregate."""
    name: str
    """User-chosen name, unique across live connections."""
    kind: str
    """Source kind, for example databricks or postgres."""
    endpoint: str
    """Base URL or host of the source."""
    credential_ref: str | None
    """External secret reference, or ``None`` when an inline token is used."""
    has_inline_credential: bool
    """Whether the connection stores an inline token."""
    default_catalog: str | None
    """Catalog to use when an import does not name one."""
    options: dict[str, str]
    """Kind-specific options."""

    @classmethod
    def from_row(cls, row: ConnectionRow) -> Self:
        """Builds the model from a read-model row."""
        return cls(
            connection_id=row.connection_id,
            name=row.name,
            kind=row.kind,
            endpoint=row.endpoint,
            credential_ref=row.credential_ref,
            has_inline_credential=row.has_inline_credential,
            default_catalog=row.default_catalog,
            options=row.options,
        )


class ImportRunResponse(BaseModel):
    """An import run as exposed to delivery clients."""

    run_id: UUID
    """ID of the import run aggregate."""
    connection_id: UUID
    """Connection the import reads from."""
    target_catalog_id: UUID
    """Catalog the import writes into."""
    source_catalog: str | None
    """Source catalog that was imported."""
    include_schemas: list[str]
    """Schemas the import was restricted to."""
    include_tables: dict[str, list[str]]
    """Tables the import was restricted to, keyed by source schema."""
    schema_mapping: dict[str, str]
    """Target schema names keyed by source schema."""
    status: str
    """Run status: pending, succeeded, failed or abandoned."""
    schema_count: int
    """Number of source schemas processed."""
    table_count: int
    """Number of source tables processed."""
    field_count: int
    """Number of source fields processed."""
    error: str | None
    """Error message when the run failed or was abandoned."""
    created_at: datetime
    """When the run was registered."""

    @classmethod
    def from_row(cls, row: ImportRunRow) -> Self:
        """Builds the model from a read-model row."""
        return cls(
            run_id=row.run_id,
            connection_id=row.connection_id,
            target_catalog_id=row.target_catalog_id,
            source_catalog=row.source_catalog,
            include_schemas=row.include_schemas,
            include_tables=row.include_tables,
            schema_mapping=row.schema_mapping,
            status=row.status,
            schema_count=row.schema_count,
            table_count=row.table_count,
            field_count=row.field_count,
            error=row.error,
            created_at=row.created_at,
        )


class SourceKindResponse(BaseModel):
    """A source kind the server can build."""

    kind: str
    """Source kind, for example databricks or postgres."""


class SourceProfileResponse(BaseModel):
    """One local credential profile a source can authenticate with."""

    name: str
    """Profile name, used as ``profile:<name>``."""
    host: str | None = None
    """Endpoint stored in the profile, when it records one."""

    @classmethod
    def from_profile(cls, profile: SourceProfile) -> Self:
        """Builds the model from the adapter value object."""
        return cls(name=profile.name, host=profile.host)


class SourceInspectResponse(BaseModel):
    """One level of an external source tree."""

    node: str
    """Inspected level: catalogs, schemas, tables or columns."""
    items: list[dict[str, Any]]
    """Inspected nodes, in source order."""


class ImportPlanResponse(BaseModel):
    """Result of ``plan_import``."""

    schema_count: int
    """Number of source schemas the import would visit."""
    table_count: int
    """Number of source tables the import would visit."""
    field_count: int
    """Number of source fields that would be upserted."""
    new_schemas: list[str]
    """Schemas missing from the target catalog."""
    new_tables: list[str]
    """Tables missing from the target catalog, as schema.table."""
    fields_to_change: list[dict[str, Any]]
    """Existing fields whose data type or nullability would change."""
    unsupported_types: list[dict[str, str]]
    """Columns whose source type cannot be mapped, with the applied policy."""
    warnings: list[str]
    """Non-fatal issues such as colliding target tables or unused mappings."""


class ConnectionTestResponse(BaseModel):
    """Result of ``test_source_connection``."""

    ok: bool
    """Whether the source answered the probe."""
    latency_ms: int
    """Probe duration in milliseconds."""
    error: str | None = None
    """Error message when the probe failed."""
