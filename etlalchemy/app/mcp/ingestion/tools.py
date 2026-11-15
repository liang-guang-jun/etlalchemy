"""Ingestion context MCP tools."""

from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from fastmcp import FastMCP
from pydantic import Field

from etlalchemy.app.bootstrap import Container
from etlalchemy.app.mcp.errors import mcp_error_guard
from etlalchemy.app.schemas.common import OkResponse
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


def register(mcp: FastMCP, container: Container) -> None:
    """Registers the ingestion tools on the given server."""

    @mcp.tool(
        name="create_source_connection",
        description=(
            "Create a connection to an external data source and return its id. "
            "Provide exactly one of credential_ref or token; a credential_ref may be "
            "a local CLI profile such as profile:DEFAULT."
        ),
    )
    async def create_source_connection(
        name: Annotated[str, Field(description="Name of the new connection.")],
        endpoint: Annotated[
            str,
            Field(
                description=(
                    "Base URL or host of the source; empty when a profile reference "
                    "supplies the host."
                )
            ),
        ] = "",
        kind: Annotated[
            str,
            Field(
                description=(
                    "Source kind. Call list_source_kinds for the available kinds, "
                    "for example databricks or postgres."
                )
            ),
        ] = "databricks",
        credential_ref: Annotated[
            str | None,
            Field(
                description=(
                    "External secret reference such as env:DBX_TOKEN or file:token, "
                    "or a local profile such as profile:DEFAULT; null when token is used."
                )
            ),
        ] = None,
        token: Annotated[
            str | None,
            Field(description="Inline secret, or null when credential_ref is used."),
        ] = None,
        default_catalog: Annotated[
            str | None,
            Field(description="Catalog to use when an import does not name one."),
        ] = None,
        options: Annotated[
            dict[str, str] | None,
            Field(description="Kind-specific options such as type_policy."),
        ] = None,
    ) -> ConnectionCreatedResponse:
        """Create a source connection."""
        with mcp_error_guard():
            connection_id = await container.ingestion_application().create_connection(
                name=name,
                kind=kind,
                endpoint=endpoint,
                credential_ref=credential_ref,
                token=token,
                default_catalog=default_catalog,
                options=options,
            )
        return ConnectionCreatedResponse(connection_id=connection_id)

    @mcp.tool(
        name="change_source_connection",
        description="Change the name, endpoint, default catalog or options of a connection.",
    )
    async def change_source_connection(
        connection_id: Annotated[UUID, Field(description="ID of the connection.")],
        name: Annotated[
            str | None,
            Field(description="New name, or null to keep the current one."),
        ] = None,
        endpoint: Annotated[
            str | None,
            Field(description="New endpoint, or null to keep the current one."),
        ] = None,
        default_catalog: Annotated[
            str | None,
            Field(description="New default catalog, or null to keep the current one."),
        ] = None,
        options: Annotated[
            dict[str, str] | None,
            Field(
                description=(
                    "New options. The whole mapping is replaced: pass {} to clear it, "
                    "or null to keep the current options."
                )
            ),
        ] = None,
    ) -> OkResponse:
        """Change a source connection."""
        with mcp_error_guard():
            await container.ingestion_application().change_connection(
                connection_id,
                name=name,
                endpoint=endpoint,
                default_catalog=default_catalog,
                options=options,
            )
        return OkResponse()

    @mcp.tool(
        name="rotate_source_credential",
        description=(
            "Replace the credential of a connection with an external reference or "
            "an inline token. Provide exactly one of credential_ref or token."
        ),
    )
    async def rotate_source_credential(
        connection_id: Annotated[UUID, Field(description="ID of the connection.")],
        credential_ref: Annotated[
            str | None,
            Field(description="New external secret reference, or null when token is used."),
        ] = None,
        token: Annotated[
            str | None,
            Field(description="New inline secret, or null when credential_ref is used."),
        ] = None,
    ) -> OkResponse:
        """Rotate a source credential."""
        with mcp_error_guard():
            await container.ingestion_application().rotate_credential(
                connection_id,
                credential_ref=credential_ref,
                token=token,
            )
        return OkResponse()

    @mcp.tool(
        name="discard_source_connection",
        description="Discard a source connection. Import runs are kept.",
        annotations={"destructiveHint": True},
    )
    async def discard_source_connection(
        connection_id: Annotated[UUID, Field(description="ID of the connection to discard.")],
    ) -> OkResponse:
        """Discard a source connection."""
        with mcp_error_guard():
            await container.ingestion_application().discard_connection(connection_id)
        return OkResponse()

    @mcp.tool(
        name="import_source_catalog",
        description=(
            "Import a source catalog into a catalog and return the finalised import run "
            "with its status and counters."
        ),
    )
    async def import_source_catalog(
        connection_id: Annotated[UUID, Field(description="ID of the source connection.")],
        target_catalog_id: Annotated[
            UUID,
            Field(description="ID of the catalog the import writes into."),
        ],
        source_catalog: Annotated[
            str | None,
            Field(description="Source catalog to import, or null for the connection default."),
        ] = None,
        include_schemas: Annotated[
            list[str] | None,
            Field(description="Only import these schemas, or null for all of them."),
        ] = None,
        include_tables: Annotated[
            dict[str, list[str]] | None,
            Field(
                description=(
                    "Restrict the import to these tables, keyed by source schema name. "
                    "A schema absent from the mapping is skipped; an empty list skips the "
                    "schema. Null imports every table of the selected schemas."
                )
            ),
        ] = None,
        schema_mapping: Annotated[
            dict[str, str] | None,
            Field(
                description=(
                    "Rename source schemas in the target catalog, keyed by source schema "
                    "name. Schemas absent from the mapping keep their name."
                )
            ),
        ] = None,
    ) -> ImportRunResponse:
        """Import a source catalog."""
        with mcp_error_guard():
            application = container.ingestion_application()
            run_id = await application.import_from(
                connection_id,
                target_catalog_id,
                source_catalog=source_catalog,
                include_schemas=include_schemas,
                include_tables=include_tables,
                schema_mapping=schema_mapping,
            )
            run = await application.get_import_run(run_id)
            if run is None:
                msg = f"Import run {run_id} disappeared after the import"
                raise RuntimeError(msg)
            return ImportRunResponse(
                run_id=run.id,
                connection_id=run.connection_id,
                target_catalog_id=run.target_catalog_id,
                source_catalog=run.source_catalog,
                include_schemas=run.include_schemas,
                include_tables=run.include_tables,
                schema_mapping=run.schema_mapping,
                status=run.status,
                schema_count=run.schema_count,
                table_count=run.table_count,
                field_count=run.field_count,
                error=run.error,
                created_at=run.created_on,
            )

    # ---- read-only tools -------------------------------------------------

    @mcp.tool(
        name="list_source_connections",
        description="List live source connections, optionally filtered by kind and paged.",
        annotations={"readOnlyHint": True},
    )
    async def list_source_connections(
        kind: Annotated[
            str | None,
            Field(description="Restrict to this source kind, or null for all."),
        ] = None,
        limit: Annotated[int, Field(description="Maximum number of rows to return.")] = 50,
        offset: Annotated[int, Field(description="Number of rows to skip.")] = 0,
    ) -> list[ConnectionResponse]:
        """List source connections."""
        with mcp_error_guard():
            rows = await container.ingestion_view().list_connections(
                kind=kind,
                limit=limit,
                offset=offset,
            )
        return [ConnectionResponse.from_row(row) for row in rows]

    @mcp.tool(
        name="get_source_connection",
        description="Return one live source connection, or null when it does not exist.",
        annotations={"readOnlyHint": True},
    )
    async def get_source_connection(
        connection_id: Annotated[UUID, Field(description="ID of the connection.")],
    ) -> ConnectionResponse | None:
        """Get a source connection."""
        with mcp_error_guard():
            row = await container.ingestion_view().get_connection(connection_id)
        return None if row is None else ConnectionResponse.from_row(row)

    @mcp.tool(
        name="list_import_runs",
        description=("List import runs, optionally filtered by connection and status, and paged."),
        annotations={"readOnlyHint": True},
    )
    async def list_import_runs(
        connection_id: Annotated[
            UUID | None,
            Field(description="Restrict to this connection, or null for all."),
        ] = None,
        status: Annotated[
            Literal["pending", "succeeded", "failed", "abandoned"] | None,
            Field(description="Restrict to this status, or null for all."),
        ] = None,
        limit: Annotated[int, Field(description="Maximum number of rows to return.")] = 50,
        offset: Annotated[int, Field(description="Number of rows to skip.")] = 0,
    ) -> list[ImportRunResponse]:
        """List import runs."""
        with mcp_error_guard():
            rows = await container.ingestion_view().list_import_runs(
                connection_id=connection_id,
                status=status,
                limit=limit,
                offset=offset,
            )
        return [ImportRunResponse.from_row(row) for row in rows]

    @mcp.tool(
        name="get_import_run",
        description="Return one import run, or null when it does not exist.",
        annotations={"readOnlyHint": True},
    )
    async def get_import_run(
        run_id: Annotated[UUID, Field(description="ID of the import run.")],
    ) -> ImportRunResponse | None:
        """Get an import run."""
        with mcp_error_guard():
            row = await container.ingestion_view().get_import_run(run_id)
        return None if row is None else ImportRunResponse.from_row(row)

    @mcp.tool(
        name="list_source_kinds",
        description="List the source kinds this server can build connections for.",
        annotations={"readOnlyHint": True},
    )
    async def list_source_kinds() -> list[SourceKindResponse]:
        """List source kinds."""
        with mcp_error_guard():
            kinds = container.ingestion_application().source_kinds()
        return [SourceKindResponse(kind=kind) for kind in kinds]

    @mcp.tool(
        name="list_source_profiles",
        description=(
            "List the local credential profiles a source kind can authenticate with, "
            "for example the Databricks CLI profiles of this machine. Secrets are "
            "never returned."
        ),
        annotations={"readOnlyHint": True},
    )
    async def list_source_profiles(
        kind: Annotated[
            str,
            Field(description="Source kind whose local profiles are listed."),
        ] = "databricks",
    ) -> list[SourceProfileResponse]:
        """List local source profiles."""
        with mcp_error_guard():
            profiles = await container.ingestion_application().source_profiles(kind)
        return [SourceProfileResponse.from_profile(profile) for profile in profiles]

    @mcp.tool(
        name="inspect_source",
        description=(
            "Inspect one level of a source tree without importing: catalogs, schemas, "
            "tables or columns. Pass table together with schema to read columns."
        ),
        annotations={"readOnlyHint": True},
    )
    async def inspect_source(
        connection_id: Annotated[UUID, Field(description="ID of the source connection.")],
        catalog: Annotated[
            str | None,
            Field(description="Source catalog to read, or null for the connection default."),
        ] = None,
        schema: Annotated[
            str | None,
            Field(description="Schema to read tables from, or null to list schemas."),
        ] = None,
        table: Annotated[
            str | None,
            Field(description="Table to read columns from; requires schema."),
        ] = None,
        limit: Annotated[int, Field(description="Maximum number of items to return.")] = 200,
    ) -> SourceInspectResponse:
        """Inspect a source tree level."""
        with mcp_error_guard():
            result = await container.ingestion_application().inspect_source(
                connection_id,
                catalog=catalog,
                schema=schema,
                table=table,
                limit=limit,
            )
        return SourceInspectResponse(node=result.node, items=result.items)

    @mcp.tool(
        name="plan_import",
        description=(
            "Compute what an import would change without writing to the catalog, "
            "including unsupported source types."
        ),
        annotations={"readOnlyHint": True},
    )
    async def plan_import(
        connection_id: Annotated[UUID, Field(description="ID of the source connection.")],
        target_catalog_id: Annotated[
            UUID,
            Field(description="ID of the catalog the import would write into."),
        ],
        source_catalog: Annotated[
            str | None,
            Field(description="Source catalog to plan, or null for the connection default."),
        ] = None,
        include_schemas: Annotated[
            list[str] | None,
            Field(description="Only plan these schemas, or null for all of them."),
        ] = None,
        include_tables: Annotated[
            dict[str, list[str]] | None,
            Field(
                description=(
                    "Restrict the plan to these tables, keyed by source schema name. "
                    "A schema absent from the mapping is skipped; an empty list skips the "
                    "schema. Null plans every table of the selected schemas."
                )
            ),
        ] = None,
        schema_mapping: Annotated[
            dict[str, str] | None,
            Field(
                description=(
                    "Rename source schemas in the target catalog, keyed by source schema "
                    "name. Schemas absent from the mapping keep their name."
                )
            ),
        ] = None,
    ) -> ImportPlanResponse:
        """Plan an import without writing."""
        with mcp_error_guard():
            plan = await container.ingestion_application().plan_import(
                connection_id,
                target_catalog_id,
                source_catalog=source_catalog,
                include_schemas=include_schemas,
                include_tables=include_tables,
                schema_mapping=schema_mapping,
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

    @mcp.tool(
        name="test_source_connection",
        description="Check whether a connection can reach its source and list its catalogs.",
        annotations={"readOnlyHint": True},
    )
    async def test_source_connection(
        connection_id: Annotated[UUID, Field(description="ID of the connection to test.")],
    ) -> ConnectionTestResponse:
        """Test a source connection."""
        with mcp_error_guard():
            result = await container.ingestion_application().test_source_connection(connection_id)
        return ConnectionTestResponse(
            ok=result.ok,
            latency_ms=result.latency_ms,
            error=result.error,
        )

    @mcp.tool(
        name="abandon_import_run",
        description=(
            "Mark a stale pending import run as abandoned. Runs that already finished are rejected."
        ),
        annotations={"destructiveHint": True},
    )
    async def abandon_import_run(
        run_id: Annotated[UUID, Field(description="ID of the pending import run.")],
        reason: Annotated[str, Field(description="Reason the run is abandoned.")],
    ) -> OkResponse:
        """Abandon a stale pending run."""
        with mcp_error_guard():
            await container.ingestion_application().abandon_import_run(run_id, reason)
        return OkResponse()
