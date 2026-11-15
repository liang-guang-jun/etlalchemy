"""Catalog context MCP tools."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastmcp import FastMCP
from pydantic import Field

from etlalchemy.app.bootstrap import Container
from etlalchemy.app.mcp.errors import mcp_error_guard
from etlalchemy.app.schemas.catalog import (
    CatalogCreatedResponse,
    FieldSearchResultResponse,
    SchemaCreatedResponse,
    TableCreatedResponse,
)
from etlalchemy.app.schemas.common import OkResponse


def register(mcp: FastMCP, container: Container) -> None:
    """Registers the catalog tools on the given server."""
    # ---- catalog level ----

    @mcp.tool(
        name="create_catalog",
        description="Create a catalog and return the id of the new aggregate.",
    )
    async def create_catalog(
        name: Annotated[str, Field(description="Name of the new catalog.")],
        description: Annotated[
            str,
            Field(description="Free-form description of the catalog."),
        ] = "",
    ) -> CatalogCreatedResponse:
        """Create a catalog."""
        with mcp_error_guard():
            catalog_id = await container.catalog_application().create_catalog(name, description)
        return CatalogCreatedResponse(catalog_id=catalog_id)

    @mcp.tool(
        name="change_catalog",
        description="Change the name and/or description of a catalog.",
    )
    async def change_catalog(
        catalog_id: Annotated[UUID, Field(description="ID of the catalog.")],
        name: Annotated[
            str | None,
            Field(description="New name, or null to keep the current one."),
        ] = None,
        description: Annotated[
            str | None,
            Field(description="New description, or null to keep the current one."),
        ] = None,
    ) -> OkResponse:
        """Change a catalog."""
        with mcp_error_guard():
            await container.catalog_application().change_catalog(catalog_id, name, description)
        return OkResponse()

    @mcp.tool(
        name="change_catalog_description",
        description="Replace the description of a catalog without touching its name.",
    )
    async def change_catalog_description(
        catalog_id: Annotated[UUID, Field(description="ID of the catalog.")],
        description: Annotated[
            str,
            Field(description="New description; an empty string clears it."),
        ],
    ) -> OkResponse:
        """Change the description of a catalog."""
        with mcp_error_guard():
            await container.catalog_application().change_catalog(
                catalog_id,
                None,
                description,
            )
        return OkResponse()

    @mcp.tool(
        name="discard_catalog",
        description="Discard a catalog together with its schemas, tables and fields.",
        annotations={"destructiveHint": True},
    )
    async def discard_catalog(
        catalog_id: Annotated[UUID, Field(description="ID of the catalog to discard.")],
    ) -> OkResponse:
        """Discard a catalog."""
        with mcp_error_guard():
            await container.catalog_application().discard_catalog(catalog_id)
        return OkResponse()

    # ---- schema level ----

    @mcp.tool(
        name="create_schema",
        description="Create a schema in a catalog and return the id of the new aggregate.",
    )
    async def create_schema(
        catalog_id: Annotated[UUID, Field(description="ID of the owning catalog.")],
        schema_name: Annotated[str, Field(description="Name of the new schema.")],
        description: Annotated[
            str,
            Field(description="Free-form description of the schema."),
        ] = "",
    ) -> SchemaCreatedResponse:
        """Create a schema."""
        with mcp_error_guard():
            schema_id = await container.catalog_application().create_schema(
                catalog_id,
                schema_name,
                description,
            )
        return SchemaCreatedResponse(schema_id=schema_id)

    @mcp.tool(
        name="change_schema",
        description="Change the name and/or description of a schema addressed by name or id.",
    )
    async def change_schema(
        catalog_id: Annotated[UUID, Field(description="ID of the owning catalog.")],
        schema: Annotated[
            str,
            Field(description="Registry name or id of the schema."),
        ],
        name: Annotated[
            str | None,
            Field(description="New name, or null to keep the current one."),
        ] = None,
        description: Annotated[
            str | None,
            Field(description="New description, or null to keep the current one."),
        ] = None,
    ) -> OkResponse:
        """Change a schema."""
        with mcp_error_guard():
            await container.catalog_application().change_schema(
                catalog_id,
                schema,
                name,
                description,
            )
        return OkResponse()

    @mcp.tool(
        name="change_schema_description",
        description="Replace the description of a schema addressed by name or id.",
    )
    async def change_schema_description(
        catalog_id: Annotated[UUID, Field(description="ID of the owning catalog.")],
        schema: Annotated[
            str,
            Field(description="Registry name or id of the schema."),
        ],
        description: Annotated[
            str,
            Field(description="New description; an empty string clears it."),
        ],
    ) -> OkResponse:
        """Change the description of a schema."""
        with mcp_error_guard():
            await container.catalog_application().change_schema(
                catalog_id,
                schema,
                None,
                description,
            )
        return OkResponse()

    @mcp.tool(
        name="discard_schema",
        description="Discard a schema addressed by name or id, together with its tables.",
        annotations={"destructiveHint": True},
    )
    async def discard_schema(
        catalog_id: Annotated[UUID, Field(description="ID of the owning catalog.")],
        schema: Annotated[
            str,
            Field(description="Registry name or id of the schema to discard."),
        ],
    ) -> OkResponse:
        """Discard a schema."""
        with mcp_error_guard():
            await container.catalog_application().discard_schema(catalog_id, schema)
        return OkResponse()

    # ---- table level ----

    @mcp.tool(
        name="add_table",
        description="Add a table to a schema addressed by name or id and return its id.",
    )
    async def add_table(
        catalog_id: Annotated[UUID, Field(description="ID of the owning catalog.")],
        schema: Annotated[
            str,
            Field(description="Registry name or id of the owning schema."),
        ],
        table_name: Annotated[str, Field(description="Name of the new table.")],
    ) -> TableCreatedResponse:
        """Add a table."""
        with mcp_error_guard():
            table_id = await container.catalog_application().add_table(
                catalog_id,
                schema,
                table_name,
            )
        return TableCreatedResponse(table_id=table_id)

    @mcp.tool(
        name="change_table",
        description="Change the name of a table addressed by name or id.",
    )
    async def change_table(
        catalog_id: Annotated[UUID, Field(description="ID of the owning catalog.")],
        schema: Annotated[
            str,
            Field(description="Registry name or id of the owning schema."),
        ],
        table: Annotated[
            str,
            Field(description="Registry name or id of the table."),
        ],
        name: Annotated[
            str | None,
            Field(description="New table name, or null to keep the current one."),
        ] = None,
    ) -> OkResponse:
        """Change a table."""
        with mcp_error_guard():
            await container.catalog_application().change_table(catalog_id, schema, table, name)
        return OkResponse()

    @mcp.tool(
        name="change_table_description",
        description="Replace the description of a table addressed by name or id.",
    )
    async def change_table_description(
        catalog_id: Annotated[UUID, Field(description="ID of the owning catalog.")],
        schema: Annotated[
            str,
            Field(description="Registry name or id of the owning schema."),
        ],
        table: Annotated[
            str,
            Field(description="Registry name or id of the table."),
        ],
        description: Annotated[
            str,
            Field(description="New description; an empty string clears it."),
        ],
    ) -> OkResponse:
        """Change the description of a table."""
        with mcp_error_guard():
            await container.catalog_application().change_table(
                catalog_id,
                schema,
                table,
                None,
                description,
            )
        return OkResponse()

    @mcp.tool(
        name="discard_table",
        description="Discard a table addressed by name or id, together with its fields.",
        annotations={"destructiveHint": True},
    )
    async def discard_table(
        catalog_id: Annotated[UUID, Field(description="ID of the owning catalog.")],
        schema: Annotated[
            str,
            Field(description="Registry name or id of the owning schema."),
        ],
        table: Annotated[
            str,
            Field(description="Registry name or id of the table to discard."),
        ],
    ) -> OkResponse:
        """Discard a table."""
        with mcp_error_guard():
            await container.catalog_application().discard_table(catalog_id, schema, table)
        return OkResponse()

    # ---- field level ----

    @mcp.tool(
        name="add_field",
        description="Add a field to a table addressed by name or id.",
    )
    async def add_field(
        catalog_id: Annotated[UUID, Field(description="ID of the owning catalog.")],
        schema: Annotated[
            str,
            Field(description="Registry name or id of the owning schema."),
        ],
        table: Annotated[
            str,
            Field(description="Registry name or id of the owning table."),
        ],
        field_name: Annotated[str, Field(description="Name of the new field.")],
        data_type: Annotated[
            str,
            Field(
                description=(
                    "Data type of the field. Canonical forms: boolean, smallint, integer, "
                    "bigint, float, double, decimal(p,s), string, varchar(n), char(n), "
                    "text, date, timestamp, timestamptz, json, binary, uuid. "
                    "Aliases such as 'str', 'int' or 'VARCHAR' are accepted and normalised."
                )
            ),
        ],
        nullable: Annotated[
            bool,
            Field(description="Whether the field may hold null values."),
        ] = True,
    ) -> OkResponse:
        """Add a field."""
        with mcp_error_guard():
            await container.catalog_application().add_field(
                catalog_id,
                schema,
                table,
                field_name,
                data_type,
                nullable,
            )
        return OkResponse()

    @mcp.tool(
        name="change_field",
        description="Change the data type and/or nullability of an existing field.",
    )
    async def change_field(
        catalog_id: Annotated[UUID, Field(description="ID of the owning catalog.")],
        schema: Annotated[
            str,
            Field(description="Registry name or id of the owning schema."),
        ],
        table: Annotated[
            str,
            Field(description="Registry name or id of the owning table."),
        ],
        field_name: Annotated[str, Field(description="Name of the field to change.")],
        data_type: Annotated[
            str | None,
            Field(
                description=(
                    "New canonical data type, or null to keep the current one. "
                    "Aliases such as 'str', 'int' or 'VARCHAR' are accepted and normalised."
                )
            ),
        ] = None,
        nullable: Annotated[
            bool | None,
            Field(description="New nullability, or null to keep the current one."),
        ] = None,
    ) -> OkResponse:
        """Change a field."""
        with mcp_error_guard():
            await container.catalog_application().change_field(
                catalog_id,
                schema,
                table,
                field_name,
                data_type,
                nullable,
            )
        return OkResponse()

    @mcp.tool(
        name="change_field_comment",
        description=(
            "Document a field of a table with a free-form comment that describes its "
            "meaning, unit or origin."
        ),
    )
    async def change_field_comment(
        catalog_id: Annotated[UUID, Field(description="ID of the owning catalog.")],
        schema: Annotated[
            str,
            Field(description="Registry name or id of the owning schema."),
        ],
        table: Annotated[
            str,
            Field(description="Registry name or id of the owning table."),
        ],
        field_name: Annotated[str, Field(description="Name of the field.")],
        comment: Annotated[
            str,
            Field(description="New comment; an empty string clears it."),
        ],
    ) -> OkResponse:
        """Comment a field."""
        with mcp_error_guard():
            await container.catalog_application().change_field_comment(
                catalog_id,
                schema,
                table,
                field_name,
                comment,
            )
        return OkResponse()

    @mcp.tool(
        name="remove_field",
        description="Remove a field from a table addressed by name or id.",
        annotations={"destructiveHint": True},
    )
    async def remove_field(
        catalog_id: Annotated[UUID, Field(description="ID of the owning catalog.")],
        schema: Annotated[
            str,
            Field(description="Registry name or id of the owning schema."),
        ],
        table: Annotated[
            str,
            Field(description="Registry name or id of the owning table."),
        ],
        field_name: Annotated[str, Field(description="Name of the field to remove.")],
    ) -> OkResponse:
        """Remove a field."""
        with mcp_error_guard():
            await container.catalog_application().remove_field(
                catalog_id,
                schema,
                table,
                field_name,
            )
        return OkResponse()

    @mcp.tool(
        name="rename_field",
        description="Rename a field of a table, keeping its data type and nullability.",
    )
    async def rename_field(
        catalog_id: Annotated[UUID, Field(description="ID of the owning catalog.")],
        schema: Annotated[
            str,
            Field(description="Registry name or id of the owning schema."),
        ],
        table: Annotated[
            str,
            Field(description="Registry name or id of the owning table."),
        ],
        old_name: Annotated[str, Field(description="Current name of the field.")],
        new_name: Annotated[str, Field(description="Name the field is renamed to.")],
    ) -> OkResponse:
        """Rename a field."""
        with mcp_error_guard():
            await container.catalog_application().rename_field(
                catalog_id,
                schema,
                table,
                old_name,
                new_name,
            )
        return OkResponse()

    @mcp.tool(
        name="search_fields",
        description=(
            "Find fields whose schema, table or field name contains the term, "
            "optionally restricted to one catalog."
        ),
        annotations={"readOnlyHint": True},
    )
    async def search_fields(
        term: Annotated[str, Field(description="Substring to look for in the names.")],
        catalog_id: Annotated[
            UUID | None,
            Field(description="Restrict the search to this catalog, or null for all."),
        ] = None,
    ) -> list[FieldSearchResultResponse]:
        """Search fields by name."""
        with mcp_error_guard():
            rows = await container.catalog_view().search_fields(term, catalog_id)
        return [FieldSearchResultResponse.from_row(row) for row in rows]
