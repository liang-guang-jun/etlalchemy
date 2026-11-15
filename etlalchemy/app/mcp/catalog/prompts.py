"""English workflow prompts for the catalog context."""

from __future__ import annotations

from typing import Annotated

from fastmcp import FastMCP
from pydantic import Field


def register(mcp: FastMCP) -> None:
    """Registers the catalog prompts on the given server."""

    @mcp.prompt(
        name="catalog-overview",
        description=(
            "Summarize all catalogs in the workspace, including their descriptions "
            "and schema counts."
        ),
    )
    def catalog_overview() -> str:
        """Return the catalog overview template."""
        return """
You are a data catalog assistant.

Read the resource at `catalog:///all` to obtain the list of all live catalogs.
For each catalog, summarize:
- its name,
- its description (mark "no description" when empty),
- the number of schemas it contains (read `catalog:///{catalog_id}/schemas` when needed).

Present the summary as a concise bulleted list.
"""

    @mcp.prompt(
        name="inspect-table",
        description="Analyze the fields of a table and flag potential design issues.",
    )
    def inspect_table(
        catalog_id: Annotated[str, Field(description="ID of the owning catalog.")],
        schema_id: Annotated[str, Field(description="ID of the owning schema.")],
        table_id: Annotated[str, Field(description="ID of the table to inspect.")],
    ) -> str:
        """Return the table inspection template."""
        uri = f"catalog:///{catalog_id}/schemas/{schema_id}/tables/{table_id}/fields"
        return f"""
Analyze the table structure available at `{uri}`.

For each field:
- explain what its `data_type` means,
- explain what its `nullable` attribute implies for consumers of this table.

Then list potential design issues, for example:
- a large number of nullable fields,
- inconsistent naming conventions,
- fields whose data type is unusually wide or loosely typed.
"""

    @mcp.prompt(
        name="find-field",
        description=("Locate a field by name across the catalog and summarize where it appears."),
    )
    def find_field(
        term: Annotated[
            str,
            Field(description="Substring to look for in schema, table or field names."),
        ],
    ) -> str:
        """Return the field lookup template."""
        return f"""
The user is looking for a field whose name contains "{term}".

Call the `search_fields` tool with `term="{term}"`, then summarize:
- which catalogs, schemas and tables contain matching fields,
- whether the same field name appears with different `data_type` or `nullable` settings,
- any naming inconsistencies across occurrences.
"""

    @mcp.prompt(
        name="rename-safely",
        description=(
            "Check whether renaming a schema, table or field would conflict with an existing name."
        ),
    )
    def rename_safely(
        catalog_id: Annotated[str, Field(description="ID of the owning catalog.")],
        schema_id: Annotated[str, Field(description="ID of the owning schema.")],
        new_name: Annotated[str, Field(description="Name the object should get.")],
        table_id: Annotated[
            str | None,
            Field(description="ID of the table when a table or field is renamed."),
        ] = None,
    ) -> str:
        """Return the safe rename template."""
        scope = (
            f"the table `catalog:///{catalog_id}/schemas/{schema_id}/tables/{table_id}`"
            if table_id
            else f"the schema `catalog:///{catalog_id}/schemas/{schema_id}`"
        )
        return f"""
The user wants to rename an object in {scope} to "{new_name}".

Before the rename:
1. Read the relevant resource to list the current children of the scope.
2. Check whether "{new_name}" already exists in that scope.
3. If it does, explain which object owns the name and why the rename would fail.
4. If it does not, confirm that the rename is safe and suggest the exact tool call
   (`change_schema` or `change_table` or `rename_field`) with the correct arguments.
"""
