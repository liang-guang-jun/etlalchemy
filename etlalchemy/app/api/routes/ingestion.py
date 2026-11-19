"""HTTP routes exposing the ingestion context."""

from __future__ import annotations

from typing import Self
from uuid import UUID

from dependency_injector.wiring import Provide, inject
from eventsourcing.persistence import RecordConflictError
from fastapi import APIRouter, Depends, FastAPI, HTTPException
from pydantic import BaseModel, Field, model_validator

from etlalchemy.app.api.errors import install_exception_handlers
from etlalchemy.app.bootstrap import Container
from etlalchemy.app.schemas.ingestion import (
    ConnectionCreatedResponse,
    ConnectionResponse,
    ConnectionTestResponse,
    ImportPlanResponse,
    ImportRunResponse,
    SourceInspectResponse,
    SourceKindResponse,
    SourceProfileResponse,
)
from etlalchemy.ingestion.aggregates.errors import IngestionError, UnknownConnectionError
from etlalchemy.ingestion.application import IngestionApplication
from etlalchemy.ingestion.projection.view import IngestionView

router = APIRouter(prefix="/ingestion", tags=["ingestion"])

CONFLICT_ERRORS = (IngestionError, RecordConflictError)
NOT_FOUND_ERRORS = (UnknownConnectionError,)


def add_exception_handlers(app: FastAPI) -> None:
    """Maps ingestion errors to HTTP responses."""
    install_exception_handlers(
        app,
        conflict=CONFLICT_ERRORS,
        not_found=NOT_FOUND_ERRORS,
        bad_request=(ValueError,),
    )


class ConnectionCreate(BaseModel):
    """Body of ``POST /ingestion/connections``."""

    name: str
    """User-chosen name, unique across live connections."""
    kind: str = "databricks"
    """Source kind, for example ``databricks``."""
    endpoint: str = ""
    """Base URL or host of the source; empty when a profile supplies the host."""
    credential_ref: str | None = None
    """External secret reference, for example ``env:DBX_TOKEN`` or ``profile:DEFAULT``."""
    token: str | None = Field(default=None, repr=False)
    """Inline secret, encrypted at rest when a cipher is configured."""
    default_catalog: str | None = None
    """Catalog to use when an import does not name one."""
    options: dict[str, str] = Field(default_factory=dict)
    """Kind-specific options, for example ``type_policy``."""

    @model_validator(mode="after")
    def _exactly_one_credential(self) -> Self:
        """Rejects a body that carries both or neither credential source."""
        if (self.credential_ref is None) == (self.token is None):
            msg = "exactly one of credential_ref / token is required"
            raise ValueError(msg)
        return self


class ConnectionPatch(BaseModel):
    """Body of ``PATCH /ingestion/connections/{connection_id}``."""

    name: str | None = None
    """New name, or ``None`` to keep the current one."""
    endpoint: str | None = None
    """New endpoint, or ``None`` to keep the current one."""
    default_catalog: str | None = None
    """New default catalog, or ``None`` to keep the current one."""
    options: dict[str, str] | None = None
    """New options, or ``None`` to keep the current one."""


class CredentialRotate(BaseModel):
    """Body of ``POST /ingestion/connections/{connection_id}/rotate``."""

    credential_ref: str | None = None
    """New external secret reference."""
    token: str | None = Field(default=None, repr=False)
    """New inline secret."""

    @model_validator(mode="after")
    def _exactly_one_credential(self) -> Self:
        """Rejects a body that carries both or neither credential source."""
        if (self.credential_ref is None) == (self.token is None):
            msg = "exactly one of credential_ref / token is required"
            raise ValueError(msg)
        return self


class ImportRequest(BaseModel):
    """Body of ``POST /ingestion/connections/{connection_id}/import``."""

    target_catalog_id: UUID
    """Catalog the import writes into."""
    source_catalog: str | None = None
    """Source catalog to import, or ``None`` for the connection default."""
    include_schemas: list[str] = Field(default_factory=list)
    """Only import these schemas when non-empty."""
    include_tables: dict[str, list[str]] | None = None
    """Only import these tables, keyed by source schema name."""
    schema_mapping: dict[str, str] | None = None
    """Rename source schemas in the target catalog."""


@router.post("/connections", status_code=201, response_model=ConnectionCreatedResponse)
@inject
async def create_connection(
    body: ConnectionCreate,
    application: IngestionApplication = Depends(  # noqa: B008
        Provide[Container.ingestion_application]
    ),
) -> ConnectionCreatedResponse:
    """Creates a connection and returns its id."""
    connection_id = await application.create_connection(**body.model_dump())
    return ConnectionCreatedResponse(connection_id=connection_id)


@router.get("/connections", response_model=list[ConnectionResponse])
@inject
async def list_connections(
    view: IngestionView = Depends(Provide[Container.ingestion_view]),  # noqa: B008
) -> list[ConnectionResponse]:
    """Lists all live connections from the read model."""
    return [ConnectionResponse.from_row(row) for row in await view.list_connections()]


@router.get("/source-kinds", response_model=list[SourceKindResponse])
@inject
async def list_source_kinds(
    application: IngestionApplication = Depends(  # noqa: B008
        Provide[Container.ingestion_application]
    ),
) -> list[SourceKindResponse]:
    """Lists the source kinds the server can build a connection for."""
    return [SourceKindResponse(kind=kind) for kind in application.source_kinds()]


@router.get("/source-profiles", response_model=list[SourceProfileResponse])
@inject
async def list_source_profiles(
    kind: str = "databricks",
    application: IngestionApplication = Depends(  # noqa: B008
        Provide[Container.ingestion_application]
    ),
) -> list[SourceProfileResponse]:
    """Lists the local credential profiles a source kind can authenticate with."""
    profiles = await application.source_profiles(kind)
    return [SourceProfileResponse.from_profile(profile) for profile in profiles]


@router.get("/connections/{connection_id}", response_model=ConnectionResponse)
@inject
async def get_connection(
    connection_id: UUID,
    view: IngestionView = Depends(Provide[Container.ingestion_view]),  # noqa: B008
) -> ConnectionResponse:
    """Returns one connection metadata row; the token is never exposed."""
    row = await view.get_connection(connection_id)
    if row is None:
        raise HTTPException(
            status_code=404,
            detail=f"Connection {connection_id} not found",
        )
    return ConnectionResponse.from_row(row)


@router.get(
    "/connections/{connection_id}/inspect",
    response_model=SourceInspectResponse,
)
@inject
async def inspect_source(
    connection_id: UUID,
    catalog: str | None = None,
    schema: str | None = None,
    table: str | None = None,
    limit: int = 200,
    application: IngestionApplication = Depends(  # noqa: B008
        Provide[Container.ingestion_application]
    ),
) -> SourceInspectResponse:
    """Inspects one level of the source tree without importing anything.

    The level is selected by the deepest parameter that is given: ``table``
    lists columns, ``schema`` lists tables, ``catalog`` lists schemas and no
    parameter lists catalogs.
    """
    inspection = await application.inspect_source(
        connection_id,
        catalog=catalog,
        schema=schema,
        table=table,
        limit=limit,
    )
    return SourceInspectResponse(node=inspection.node, items=inspection.items)


@router.post("/connections/{connection_id}/test", response_model=ConnectionTestResponse)
@inject
async def probe_connection(
    connection_id: UUID,
    application: IngestionApplication = Depends(  # noqa: B008
        Provide[Container.ingestion_application]
    ),
) -> ConnectionTestResponse:
    """Probes the source and reports whether it answers."""
    result = await application.test_source_connection(connection_id)
    return ConnectionTestResponse(
        ok=result.ok,
        latency_ms=result.latency_ms,
        error=result.error,
    )


@router.post("/connections/{connection_id}/plan", response_model=ImportPlanResponse)
@inject
async def plan_import(
    connection_id: UUID,
    body: ImportRequest,
    application: IngestionApplication = Depends(  # noqa: B008
        Provide[Container.ingestion_application]
    ),
) -> ImportPlanResponse:
    """Previews an import without writing to the target catalog.

    Takes the same body as the import command because the plan depends on the
    nested ``include_tables`` / ``schema_mapping`` filters; it is a ``POST``
    only because of that payload and never mutates state.
    """
    plan = await application.plan_import(
        connection_id,
        body.target_catalog_id,
        source_catalog=body.source_catalog,
        include_schemas=body.include_schemas,
        include_tables=body.include_tables,
        schema_mapping=body.schema_mapping,
    )
    return ImportPlanResponse(
        schema_count=plan.schema_count,
        table_count=plan.table_count,
        field_count=plan.field_count,
        new_schemas=plan.new_schemas,
        new_tables=plan.new_tables,
        fields_to_change=plan.fields_to_change,
        unsupported_types=plan.unsupported_types,
        warnings=plan.warnings,
    )


@router.patch("/connections/{connection_id}")
@inject
async def change_connection(
    connection_id: UUID,
    body: ConnectionPatch,
    application: IngestionApplication = Depends(  # noqa: B008
        Provide[Container.ingestion_application]
    ),
) -> dict[str, bool]:
    """Changes connection metadata without touching the credential."""
    await application.change_connection(
        connection_id,
        name=body.name,
        endpoint=body.endpoint,
        default_catalog=body.default_catalog,
        options=body.options,
    )
    return {"ok": True}


@router.post("/connections/{connection_id}/rotate")
@inject
async def rotate_credential(
    connection_id: UUID,
    body: CredentialRotate,
    application: IngestionApplication = Depends(  # noqa: B008
        Provide[Container.ingestion_application]
    ),
) -> dict[str, bool]:
    """Replaces the connection credential."""
    await application.rotate_credential(
        connection_id,
        credential_ref=body.credential_ref,
        token=body.token,
    )
    return {"ok": True}


@router.delete("/connections/{connection_id}", status_code=204)
@inject
async def discard_connection(
    connection_id: UUID,
    application: IngestionApplication = Depends(  # noqa: B008
        Provide[Container.ingestion_application]
    ),
) -> None:
    """Discards a connection."""
    await application.discard_connection(connection_id)


@router.post("/connections/{connection_id}/import")
@inject
async def start_import(
    connection_id: UUID,
    body: ImportRequest,
    application: IngestionApplication = Depends(  # noqa: B008
        Provide[Container.ingestion_application]
    ),
) -> dict[str, str]:
    """Runs an import synchronously and returns the run id."""
    run_id = await application.import_from(
        connection_id,
        body.target_catalog_id,
        source_catalog=body.source_catalog,
        include_schemas=body.include_schemas,
        include_tables=body.include_tables,
        schema_mapping=body.schema_mapping,
    )
    return {"run_id": str(run_id)}


@router.get("/runs", response_model=list[ImportRunResponse])
@inject
async def list_runs(
    connection_id: UUID | None = None,
    status: str | None = None,
    view: IngestionView = Depends(Provide[Container.ingestion_view]),  # noqa: B008
) -> list[ImportRunResponse]:
    """Lists import runs, optionally filtered."""
    return [
        ImportRunResponse.from_row(row)
        for row in await view.list_import_runs(connection_id=connection_id, status=status)
    ]


@router.get("/runs/{run_id}", response_model=ImportRunResponse)
@inject
async def get_run(
    run_id: UUID,
    view: IngestionView = Depends(Provide[Container.ingestion_view]),  # noqa: B008
) -> ImportRunResponse:
    """Returns one import run from the read model."""
    row = await view.get_import_run(run_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Import run {run_id} not found")
    return ImportRunResponse.from_row(row)
