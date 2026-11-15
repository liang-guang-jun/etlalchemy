"""HTTP routes exposing the catalog context."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any
from uuid import UUID

from dependency_injector.wiring import Provide, inject
from eventsourcing.application import AggregateNotFoundError
from eventsourcing.persistence import RecordConflictError
from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from etlalchemy.app.bootstrap import Container
from etlalchemy.app.schemas.catalog import (
    CatalogCreatedResponse,
    CatalogObjectSearchResponse,
    FieldResponse,
    FieldSearchResultResponse,
    SchemaCreatedResponse,
    TableCreatedResponse,
    TableLocationResponse,
)
from etlalchemy.catalog.aggregates.errors import (
    DiscardedError,
    DuplicateFieldError,
    DuplicateSchemaError,
    DuplicateTableError,
    InvalidDataTypeError,
    UnknownFieldError,
    UnknownSchemaError,
    UnknownTableError,
)
from etlalchemy.catalog.application import CatalogApplication
from etlalchemy.catalog.projection.view import (
    CatalogView,
    SchemaRow,
    TableRow,
)
from etlalchemy.shared.utils import uuid_or_none

router = APIRouter(prefix="/catalog", tags=["catalog"])

CONFLICT_ERRORS = (
    DuplicateSchemaError,
    DuplicateTableError,
    DuplicateFieldError,
    InvalidDataTypeError,
    DiscardedError,
    RecordConflictError,
)
NOT_FOUND_ERRORS = (
    UnknownSchemaError,
    UnknownTableError,
    UnknownFieldError,
    AggregateNotFoundError,
)


def _error_handler(status_code: int) -> Any:
    """Builds a handler that renders the error message with the given status."""

    async def handler(request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(status_code=status_code, content={"detail": str(exc)})

    return handler


async def _schema_row(view: CatalogView, catalog_id: UUID, schema: str) -> SchemaRow:
    """Returns the schema addressed by its registry name or by its id."""
    schema_id = await view.find_schema_id(catalog_id, schema) or uuid_or_none(schema)
    row = None if schema_id is None else await view.get_schema(schema_id)
    if row is None or row.catalog_id != catalog_id:
        msg = f"Schema {schema!r} does not exist in catalog {catalog_id}"
        raise UnknownSchemaError(msg)
    return row


async def _table_row(view: CatalogView, schema_id: UUID, table: str) -> TableRow:
    """Returns the table addressed by its registry name or by its id."""
    table_id = await view.find_table_id(schema_id, table) or uuid_or_none(table)
    row = None if table_id is None else await view.get_table(table_id)
    if row is None or row.schema_id != schema_id:
        msg = f"Table {table!r} does not exist in schema {schema_id}"
        raise UnknownTableError(msg)
    return row


def add_exception_handlers(app: FastAPI) -> None:
    """Maps catalog errors to HTTP responses."""
    for conflict_error in CONFLICT_ERRORS:
        app.add_exception_handler(conflict_error, _error_handler(409))
    for missing_error in NOT_FOUND_ERRORS:
        app.add_exception_handler(missing_error, _error_handler(404))
    app.add_exception_handler(ValueError, _error_handler(400))


@router.post("/catalogs", response_model=CatalogCreatedResponse)
@inject
async def create_catalog(
    name: str,
    description: str = "",
    app: CatalogApplication = Depends(  # noqa: B008
        Provide[Container.catalog_application]
    ),
) -> CatalogCreatedResponse:
    """Creates a catalog and returns its ID."""
    return CatalogCreatedResponse(catalog_id=await app.create_catalog(name, description))


@router.get("/catalogs")
@inject
async def list_catalogs(
    view: CatalogView = Depends(Provide[Container.catalog_view]),  # noqa: B008
) -> list[dict[str, Any]]:
    """Lists all catalogs from the read model."""
    return [asdict(row) for row in await view.list_catalogs()]


@router.get("/catalogs/{catalog_id}")
@inject
async def get_catalog(
    catalog_id: UUID,
    view: CatalogView = Depends(Provide[Container.catalog_view]),  # noqa: B008
) -> dict[str, Any]:
    """Returns a catalog from the read model."""
    row = await view.get_catalog(catalog_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Catalog {catalog_id} not found")
    return asdict(row)


@router.post("/catalogs/{catalog_id}/schemas", response_model=SchemaCreatedResponse)
@inject
async def create_schema(
    catalog_id: UUID,
    schema_name: str,
    description: str = "",
    app: CatalogApplication = Depends(  # noqa: B008
        Provide[Container.catalog_application]
    ),
) -> SchemaCreatedResponse:
    """Creates a schema in a catalog and returns its ID."""
    schema_id = await app.create_schema(catalog_id, schema_name, description)
    return SchemaCreatedResponse(schema_id=schema_id)


@router.get("/catalogs/{catalog_id}/schemas")
@inject
async def list_schemas(
    catalog_id: UUID,
    view: CatalogView = Depends(Provide[Container.catalog_view]),  # noqa: B008
) -> list[dict[str, Any]]:
    """Lists the schemas of a catalog from the read model."""
    return [asdict(row) for row in await view.list_schemas(catalog_id)]


@router.get("/catalogs/{catalog_id}/schemas/{schema}")
@inject
async def get_schema(
    catalog_id: UUID,
    schema: str,
    view: CatalogView = Depends(Provide[Container.catalog_view]),  # noqa: B008
) -> dict[str, Any]:
    """Returns a schema addressed by name or id from the read model."""
    return asdict(await _schema_row(view, catalog_id, schema))


@router.post(
    "/catalogs/{catalog_id}/schemas/{schema}/tables",
    response_model=TableCreatedResponse,
)
@inject
async def add_table(
    catalog_id: UUID,
    schema: str,
    table_name: str,
    app: CatalogApplication = Depends(  # noqa: B008
        Provide[Container.catalog_application]
    ),
) -> TableCreatedResponse:
    """Adds a table to a schema addressed by name or id and returns its ID."""
    return TableCreatedResponse(table_id=await app.add_table(catalog_id, schema, table_name))


@router.get("/catalogs/{catalog_id}/schemas/{schema}/tables")
@inject
async def list_tables(
    catalog_id: UUID,
    schema: str,
    view: CatalogView = Depends(Provide[Container.catalog_view]),  # noqa: B008
) -> list[dict[str, Any]]:
    """Lists the tables of a schema addressed by name or id."""
    row = await _schema_row(view, catalog_id, schema)
    return [asdict(table) for table in await view.list_tables(row.schema_id)]


@router.get("/catalogs/{catalog_id}/schemas/{schema}/tables/{table}")
@inject
async def get_table(
    catalog_id: UUID,
    schema: str,
    table: str,
    view: CatalogView = Depends(Provide[Container.catalog_view]),  # noqa: B008
) -> dict[str, Any]:
    """Returns a table addressed by name or id from the read model."""
    schema_row = await _schema_row(view, catalog_id, schema)
    return asdict(await _table_row(view, schema_row.schema_id, table))


@router.post("/catalogs/{catalog_id}/schemas/{schema}/tables/{table}/fields")
@inject
async def add_field(
    catalog_id: UUID,
    schema: str,
    table: str,
    field_name: str,
    data_type: str,
    nullable: bool = True,
    app: CatalogApplication = Depends(  # noqa: B008
        Provide[Container.catalog_application]
    ),
) -> dict[str, bool]:
    """Adds a field to a table addressed by name or id."""
    await app.add_field(catalog_id, schema, table, field_name, data_type, nullable)
    return {"ok": True}


@router.get(
    "/catalogs/{catalog_id}/schemas/{schema}/tables/{table}/fields",
    response_model=list[FieldResponse],
)
@inject
async def list_fields(
    catalog_id: UUID,
    schema: str,
    table: str,
    view: CatalogView = Depends(Provide[Container.catalog_view]),  # noqa: B008
) -> list[FieldResponse]:
    """Lists the fields of a table addressed by name or id."""
    schema_row = await _schema_row(view, catalog_id, schema)
    table_row = await _table_row(view, schema_row.schema_id, table)
    return [FieldResponse.from_row(field) for field in await view.list_fields(table_row.table_id)]


@router.get("/tables/{table_id}", response_model=TableLocationResponse)
@inject
async def get_table_location(
    table_id: UUID,
    view: CatalogView = Depends(Provide[Container.catalog_view]),  # noqa: B008
) -> TableLocationResponse:
    """Returns a table with the names of the schema and catalog that own it.

    Contexts that only keep a ``table_id`` — the semantic entities, for instance —
    use this to render a readable ``schema.table`` path and to link to the table.
    """
    table = await view.get_table(table_id)
    schema = None if table is None else await view.get_schema(table.schema_id)
    if table is None or schema is None:
        msg = f"Table {table_id} does not exist"
        raise UnknownTableError(msg)
    return TableLocationResponse(
        table_id=table.table_id,
        name=table.name,
        catalog_id=table.catalog_id,
        schema_id=schema.schema_id,
        schema_name=schema.name,
    )


@router.get("/tables/{table_id}/fields", response_model=list[FieldResponse])
@inject
async def list_fields_of_table(
    table_id: UUID,
    view: CatalogView = Depends(Provide[Container.catalog_view]),  # noqa: B008
) -> list[FieldResponse]:
    """Lists the fields of a table addressed by its id alone.

    Other contexts only store the ``table_id`` of the tables they refer to, so
    they need this entry point to resolve the fields without walking the
    catalog/schema path first.
    """
    if await view.get_table(table_id) is None:
        msg = f"Table {table_id} does not exist"
        raise UnknownTableError(msg)
    return [FieldResponse.from_row(field) for field in await view.list_fields(table_id)]


@router.get("/search", response_model=list[FieldSearchResultResponse])
@inject
async def search_fields(
    term: str,
    catalog_id: UUID | None = None,
    view: CatalogView = Depends(Provide[Container.catalog_view]),  # noqa: B008
) -> list[FieldSearchResultResponse]:
    """Searches fields by schema, table or field name."""
    return [
        FieldSearchResultResponse.from_row(result)
        for result in await view.search_fields(term, catalog_id)
    ]


@router.get("/search-objects", response_model=list[CatalogObjectSearchResponse])
@inject
async def search_objects(
    term: str,
    catalog_id: UUID | None = None,
    view: CatalogView = Depends(Provide[Container.catalog_view]),  # noqa: B008
) -> list[CatalogObjectSearchResponse]:
    """Searches catalogs, schemas, tables and fields by their own name."""
    needle = term.strip()
    if needle == "":
        return []
    return [
        CatalogObjectSearchResponse.from_row(result)
        for result in await view.search_objects(needle, catalog_id)
    ]


class CatalogPatch(BaseModel):
    """Editable attributes of a catalog."""

    name: str | None = None
    """New name, or ``None`` to keep the current one."""
    description: str | None = None
    """New description, or ``None`` to keep the current one."""


class SchemaPatch(BaseModel):
    """Editable attributes of a schema."""

    name: str | None = None
    """New name, or ``None`` to keep the current one."""
    description: str | None = None
    """New description, or ``None`` to keep the current one."""


class TablePatch(BaseModel):
    """Editable attributes of a table."""

    name: str | None = None
    """New name, or ``None`` to keep the current one."""
    description: str | None = None
    """New description, or ``None`` to keep the current one."""


class FieldPatch(BaseModel):
    """Editable attributes of a field."""

    data_type: str | None = None
    """New data type, or ``None`` to keep the current one."""
    nullable: bool | None = None
    """New nullability, or ``None`` to keep the current one."""
    comment: str | None = None
    """New comment, or ``None`` to keep the current one."""


class FieldRename(BaseModel):
    """New name of a field."""

    new_name: str
    """Name the field is renamed to."""


@router.patch("/catalogs/{catalog_id}")
@inject
async def change_catalog(
    catalog_id: UUID,
    body: CatalogPatch,
    app: CatalogApplication = Depends(  # noqa: B008
        Provide[Container.catalog_application]
    ),
) -> dict[str, bool]:
    """Changes the name and/or description of a catalog."""
    await app.change_catalog(catalog_id, body.name, body.description)
    return {"ok": True}


@router.delete("/catalogs/{catalog_id}", status_code=204)
@inject
async def discard_catalog(
    catalog_id: UUID,
    app: CatalogApplication = Depends(  # noqa: B008
        Provide[Container.catalog_application]
    ),
) -> None:
    """Discards a catalog and everything it owns."""
    await app.discard_catalog(catalog_id)


@router.patch("/catalogs/{catalog_id}/schemas/{schema}")
@inject
async def change_schema(
    catalog_id: UUID,
    schema: str,
    body: SchemaPatch,
    app: CatalogApplication = Depends(  # noqa: B008
        Provide[Container.catalog_application]
    ),
) -> dict[str, bool]:
    """Changes the name and/or description of a schema addressed by name or id."""
    await app.change_schema(catalog_id, schema, body.name, body.description)
    return {"ok": True}


@router.delete("/catalogs/{catalog_id}/schemas/{schema}", status_code=204)
@inject
async def discard_schema(
    catalog_id: UUID,
    schema: str,
    app: CatalogApplication = Depends(  # noqa: B008
        Provide[Container.catalog_application]
    ),
) -> None:
    """Discards a schema addressed by name or id and its tables."""
    await app.discard_schema(catalog_id, schema)


@router.patch("/catalogs/{catalog_id}/schemas/{schema}/tables/{table}")
@inject
async def change_table(
    catalog_id: UUID,
    schema: str,
    table: str,
    body: TablePatch,
    app: CatalogApplication = Depends(  # noqa: B008
        Provide[Container.catalog_application]
    ),
) -> dict[str, bool]:
    """Changes the name and/or description of a table addressed by name or id."""
    await app.change_table(catalog_id, schema, table, body.name, body.description)
    return {"ok": True}


@router.delete(
    "/catalogs/{catalog_id}/schemas/{schema}/tables/{table}",
    status_code=204,
)
@inject
async def discard_table(
    catalog_id: UUID,
    schema: str,
    table: str,
    app: CatalogApplication = Depends(  # noqa: B008
        Provide[Container.catalog_application]
    ),
) -> None:
    """Discards a table addressed by name or id and its fields."""
    await app.discard_table(catalog_id, schema, table)


@router.patch("/catalogs/{catalog_id}/schemas/{schema}/tables/{table}/fields/{field_name}")
@inject
async def change_field(
    catalog_id: UUID,
    schema: str,
    table: str,
    field_name: str,
    body: FieldPatch,
    app: CatalogApplication = Depends(  # noqa: B008
        Provide[Container.catalog_application]
    ),
) -> dict[str, bool]:
    """Changes the data type, nullability and/or comment of a field."""
    if body.data_type is None and body.nullable is None and body.comment is None:
        raise ValueError("patch body must change at least one attribute")
    if body.data_type is not None or body.nullable is not None:
        await app.change_field(
            catalog_id,
            schema,
            table,
            field_name,
            body.data_type,
            body.nullable,
        )
    if body.comment is not None:
        await app.change_field_comment(
            catalog_id,
            schema,
            table,
            field_name,
            body.comment,
        )
    return {"ok": True}


@router.delete(
    "/catalogs/{catalog_id}/schemas/{schema}/tables/{table}/fields/{field_name}",
    status_code=204,
)
@inject
async def remove_field(
    catalog_id: UUID,
    schema: str,
    table: str,
    field_name: str,
    app: CatalogApplication = Depends(  # noqa: B008
        Provide[Container.catalog_application]
    ),
) -> None:
    """Removes a field from a table addressed by name or id."""
    await app.remove_field(catalog_id, schema, table, field_name)


@router.post("/catalogs/{catalog_id}/schemas/{schema}/tables/{table}/fields/{field_name}/rename")
@inject
async def rename_field(
    catalog_id: UUID,
    schema: str,
    table: str,
    field_name: str,
    body: FieldRename,
    app: CatalogApplication = Depends(  # noqa: B008
        Provide[Container.catalog_application]
    ),
) -> dict[str, bool]:
    """Renames a field of a table addressed by name or id."""
    await app.rename_field(catalog_id, schema, table, field_name, body.new_name)
    return {"ok": True}
