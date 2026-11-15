"""English workflow prompts for the semantic context."""

from __future__ import annotations

from typing import Annotated

from fastmcp import FastMCP
from pydantic import Field


def register(mcp: FastMCP) -> None:
    """Registers the semantic prompts on the given server."""

    @mcp.prompt(
        name="model-from-catalog",
        description=(
            "Turn a set of catalog tables into a semantic model with entities and relationships."
        ),
    )
    def model_from_catalog(
        catalog_id: Annotated[str, Field(description="ID of the catalog to model.")],
    ) -> str:
        """Return the model-building workflow template."""
        catalog_uri = f"catalog:///{catalog_id}"
        return f"""
The user wants a semantic model built from the catalog at `{catalog_uri}`.

1. Read `{catalog_uri}` to list the schemas, then the tables of the schemas the
   user cares about.
2. Propose the table list and the entity names for it, and wait for confirmation.
3. Call `create_model`, then `add_entity` once per confirmed table, passing the
   table id and a business-oriented entity name.
4. Read the candidate foreign keys from the catalog. For each one, call
   `add_relationship` with paired `from_refs` and `to_refs` of equal length and
   an explicit `cardinality`.
5. Finish with `move_node` on diagram "All" to spread the entities out, then add
   one focused diagram with `add_diagram` and `place_node`.

The All diagram always shows every entity, so never call `place_node` or
`remove_node` on it.
"""

    @mcp.prompt(
        name="review-model",
        description="Review a semantic model for orphan entities and inconsistent relationships.",
    )
    def review_model(
        model_id: Annotated[str, Field(description="ID of the model to review.")],
    ) -> str:
        """Return the model review template."""
        return f"""
Review the semantic model at `semantic:///models/{model_id}`.

1. Read `semantic:///models/{model_id}/entities` and
   `semantic:///models/{model_id}/relationships`.
2. Report every entity that no relationship mentions.
3. Report every relationship whose `from_refs` and `to_refs` have different
   lengths, and any `one_to_one` relationship that pairs more than one field.
4. Read `semantic:///models/{model_id}/diagrams` and report entities that no
   focused diagram shows.
5. Summarize the findings as a list of concrete fixes; do not change the model
   without asking the user first.
"""
