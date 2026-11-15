"""English workflow prompts for the vocabulary context."""

from __future__ import annotations

from typing import Annotated

from fastmcp import FastMCP
from pydantic import Field


def register(mcp: FastMCP) -> None:
    """Registers the vocabulary prompts on the given server."""

    @mcp.prompt(
        name="define-field",
        description=(
            "Find or create the business glossary term that defines one field of a table."
        ),
    )
    def define_field(
        catalog_id: Annotated[str, Field(description="ID of the owning catalog.")],
        schema_id: Annotated[str, Field(description="ID of the owning schema.")],
        table_id: Annotated[str, Field(description="ID of the owning table.")],
        field_name: Annotated[str, Field(description="Name of the field to define.")],
    ) -> str:
        """Return the field definition workflow template."""
        fields_uri = f"catalog:///{catalog_id}/schemas/{schema_id}/tables/{table_id}/fields"
        return f"""
The user wants to define the business meaning of the field "{field_name}" of the
table at `{fields_uri}`.

1. Call `list_terms_for_field` with `table_id="{table_id}"` and
   `field_name="{field_name}"`.
2. If a term is returned, summarize its definition, status and path, and stop.
3. If no term is returned, read `{fields_uri}` to inspect the field type and its
   neighbours, then propose a definition and two or three aliases.
4. After the user confirms, call `list_terms` to pick the domain and find a
   suitable parent category, then call `create_term` with that `parent`.
5. Link the new term with `link_term`, passing `target_kind="field"`,
   `target_id="{table_id}"` and `field_name="{field_name}"`.

Never approve the term on the user's behalf; leave it as a draft.
"""

    @mcp.prompt(
        name="review-vocabulary",
        description=("Review the draft terms of a domain, including the shape of the term tree."),
    )
    def review_vocabulary(
        domain_id: Annotated[str, Field(description="ID of the domain to review.")],
    ) -> str:
        """Return the vocabulary review template."""
        terms_uri = f"vocabulary:///domains/{domain_id}/terms"
        return f"""
Review the vocabulary at `{terms_uri}`.

1. Call `list_terms` with `domain_id="{domain_id}"` and `status="draft"`.
2. For every draft term, check that:
   - the definition is a complete sentence and is not empty,
   - the aliases do not collide with another term of the same domain,
   - every catalog link still resolves (call `get_term` and look for `dangling`).
3. Check the tree: call `list_children` for the top level and for every category,
   and report categories with no children and terms whose definition suggests
   they are misplaced.
4. For a term that passes every check, call `approve_term` with a short reviewer
   name.
5. For a term that fails, keep it as a draft and list the concrete changes the
   author must make with `change_term_definition`, `add_term_alias`,
   `remove_term_alias`, `rename_term` or `move_term`.

Report the approved terms and the rejected ones separately.
"""

    @mcp.prompt(
        name="explain-table",
        description="Explain a table field by field using the business glossary.",
    )
    def explain_table(
        catalog_id: Annotated[str, Field(description="ID of the owning catalog.")],
        schema_id: Annotated[str, Field(description="ID of the owning schema.")],
        table_id: Annotated[str, Field(description="ID of the table to explain.")],
    ) -> str:
        """Return the table explanation template."""
        fields_uri = f"catalog:///{catalog_id}/schemas/{schema_id}/tables/{table_id}/fields"
        table_uri = f"catalog:///{catalog_id}/schemas/{schema_id}/tables/{table_id}"
        return f"""
Explain the table at `{table_uri}` to a business audience.

1. Read `{fields_uri}` to get the fields, their data types and nullability.
2. Call `list_terms_for_table` with `table_id="{table_id}"` to get the terms linked
   to the table and to any of its fields.
3. Call `list_terms_for_field` for each field that still has no explanation.
4. For every field, prefer the field-level term over a table-level term, and quote
   its definition together with its path. When no term exists, say that the field
   is undocumented.
5. Finish with a short list of undocumented fields the team should add to the
   vocabulary.
"""
