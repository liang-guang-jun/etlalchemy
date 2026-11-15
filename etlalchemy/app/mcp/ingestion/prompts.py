"""English workflow prompts for the ingestion context."""

from __future__ import annotations

from fastmcp import FastMCP


def register(mcp: FastMCP) -> None:
    """Registers the ingestion prompts on the given server."""

    @mcp.prompt(
        name="import-catalog-workflow",
        description=(
            "Walk through importing a source catalog into a target catalog and "
            "confirm the result of the import run."
        ),
    )
    def import_catalog_workflow() -> str:
        """Return the import workflow template."""
        return """
You are a data ingestion assistant.

1. Read `ingestion:///connections` to list the available source connections.
2. Read `catalog:///all` to list the target catalogs.
3. If the user did not name a connection or a target catalog, ask for them before
   changing anything.
4. When the user names a subset of tables or a target schema name, build
   `include_tables` (source schema -> table names) and `schema_mapping`
   (source schema -> target schema) for the tool call. Tables absent from
   `include_tables` are not imported; an empty list skips the schema. Schemas
   absent from `schema_mapping` keep their name.
5. Call the `plan_import` tool with the same filters first and review
   `new_schemas`, `new_tables` and `warnings`; then call `import_source_catalog`
   with the connection id, the target catalog id and the same filters.
6. Read `ingestion:///runs/{run_id}` with the returned run id and report the final
   status together with the schema, table and field counters.
7. If the run failed, explain the recorded error and suggest a corrected call.
"""
