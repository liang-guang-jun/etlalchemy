"""Catalog context MCP resources.

Every resource returns ``application/json`` text. Reading a resource never fails
because an object is missing: unknown or malformed references answer ``null`` or
``[]``.
"""

from __future__ import annotations

from dataclasses import asdict

from fastmcp import FastMCP

from etlalchemy.app.bootstrap import Container
from etlalchemy.app.schemas.catalog import FieldResponse
from etlalchemy.shared.utils import dump, uuid_or_none


def register(mcp: FastMCP, container: Container) -> None:
    """Registers the catalog resources on the given server."""
    # ---- catalog level ----

    @mcp.resource(
        "catalog:///all",
        name="all-catalogs",
        description="All live catalogs, ordered by name.",
        mime_type="application/json",
    )
    async def all_catalogs() -> str:
        """Return every live catalog."""
        rows = [asdict(row) for row in await container.catalog_view().list_catalogs()]
        return dump(rows)

    @mcp.resource(
        "catalog:///{catalog_id}",
        name="catalog",
        description="One live catalog, or null when it does not exist.",
        mime_type="application/json",
    )
    async def catalog(catalog_id: str) -> str:
        """Return one catalog by id."""
        key = uuid_or_none(catalog_id)
        row = None if key is None else await container.catalog_view().get_catalog(key)
        return dump(None if row is None else asdict(row))

    # ---- schema level ----

    @mcp.resource(
        "catalog:///{catalog_id}/schemas",
        name="catalog-schemas",
        description="All live schemas of a catalog, ordered by name.",
        mime_type="application/json",
    )
    async def catalog_schemas(catalog_id: str) -> str:
        """Return the schemas of a catalog."""
        key = uuid_or_none(catalog_id)
        if key is None:
            return dump([])
        rows = [asdict(row) for row in await container.catalog_view().list_schemas(key)]
        return dump(rows)

    @mcp.resource(
        "catalog:///{catalog_id}/schemas/{schema_id}",
        name="catalog-schema",
        description="One schema of a catalog, or null when it does not exist.",
        mime_type="application/json",
    )
    async def catalog_schema(catalog_id: str, schema_id: str) -> str:
        """Return one schema of a catalog by id."""
        catalog_key = uuid_or_none(catalog_id)
        schema_key = uuid_or_none(schema_id)
        row = None if schema_key is None else await container.catalog_view().get_schema(schema_key)
        if row is None or catalog_key is None or row.catalog_id != catalog_key:
            return dump(None)
        return dump(asdict(row))

    # ---- table level ----

    @mcp.resource(
        "catalog:///{catalog_id}/schemas/{schema_id}/tables",
        name="schema-tables",
        description="All live tables of a schema, ordered by name.",
        mime_type="application/json",
    )
    async def schema_tables(catalog_id: str, schema_id: str) -> str:
        """Return the tables of a schema."""
        key = uuid_or_none(schema_id)
        if key is None:
            return dump([])
        rows = [asdict(row) for row in await container.catalog_view().list_tables(key)]
        return dump(rows)

    @mcp.resource(
        "catalog:///{catalog_id}/schemas/{schema_id}/tables/{table_id}",
        name="schema-table",
        description="One table of a schema, or null when it does not exist.",
        mime_type="application/json",
    )
    async def schema_table(catalog_id: str, schema_id: str, table_id: str) -> str:
        """Return one table of a schema by id."""
        schema_key = uuid_or_none(schema_id)
        table_key = uuid_or_none(table_id)
        row = None if table_key is None else await container.catalog_view().get_table(table_key)
        if row is None or schema_key is None or row.schema_id != schema_key:
            return dump(None)
        return dump(asdict(row))

    # ---- field level ----

    @mcp.resource(
        "catalog:///{catalog_id}/schemas/{schema_id}/tables/{table_id}/fields",
        name="table-fields",
        description="All fields of a table, ordered by name.",
        mime_type="application/json",
    )
    async def table_fields(catalog_id: str, schema_id: str, table_id: str) -> str:
        """Return the fields of a table."""
        key = uuid_or_none(table_id)
        if key is None:
            return dump([])
        rows = [
            FieldResponse.from_row(row).model_dump(mode="json")
            for row in await container.catalog_view().list_fields(key)
        ]
        return dump(rows)
