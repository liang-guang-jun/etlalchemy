"""Semantic context MCP resources.

Every resource answers ``application/json`` text and returns ``null`` or ``[]``
instead of raising when the model, diagram or id is unknown.
"""

from __future__ import annotations

from fastmcp import FastMCP

from etlalchemy.app.bootstrap import Container
from etlalchemy.app.schemas.semantic import (
    DiagramResponse,
    EntityResponse,
    ModelResponse,
    NodeResponse,
    RelationshipResponse,
)
from etlalchemy.shared.utils import dump, uuid_or_none


def register(mcp: FastMCP, container: Container) -> None:
    """Registers the semantic resources on the given server."""

    @mcp.resource(
        "semantic:///models",
        name="all-models",
        description="All live semantic models, ordered by name.",
        mime_type="application/json",
    )
    async def all_models() -> str:
        """Return every live model."""
        rows = [
            ModelResponse.from_row(row) for row in await container.semantic_view().list_models()
        ]
        return dump([row.model_dump(mode="json") for row in rows])

    @mcp.resource(
        "semantic:///models/{model_id}",
        name="model",
        description="One live model, or null when it does not exist.",
        mime_type="application/json",
    )
    async def model(model_id: str) -> str:
        """Return one model by id."""
        key = uuid_or_none(model_id)
        row = None if key is None else await container.semantic_view().get_model(key)
        return dump(None if row is None else ModelResponse.from_row(row).model_dump(mode="json"))

    @mcp.resource(
        "semantic:///models/{model_id}/entities",
        name="model-entities",
        description="The entities of a model, ordered by name.",
        mime_type="application/json",
    )
    async def model_entities(model_id: str) -> str:
        """Return the entities of a model."""
        key = uuid_or_none(model_id)
        if key is None:
            return dump([])
        rows = [
            EntityResponse.from_row(row)
            for row in await container.semantic_view().list_entities(key)
        ]
        return dump([row.model_dump(mode="json") for row in rows])

    @mcp.resource(
        "semantic:///models/{model_id}/relationships",
        name="model-relationships",
        description="The relationships of a model with both of their sides.",
        mime_type="application/json",
    )
    async def model_relationships(model_id: str) -> str:
        """Return the relationships of a model."""
        key = uuid_or_none(model_id)
        if key is None:
            return dump([])
        rows = [
            RelationshipResponse.from_row(row)
            for row in await container.semantic_view().list_relationships(key)
        ]
        return dump([row.model_dump(mode="json") for row in rows])

    @mcp.resource(
        "semantic:///models/{model_id}/diagrams",
        name="model-diagrams",
        description="The diagrams of a model, ordered by sort hint and name.",
        mime_type="application/json",
    )
    async def model_diagrams(model_id: str) -> str:
        """Return the diagrams of a model."""
        key = uuid_or_none(model_id)
        if key is None:
            return dump([])
        rows = [
            DiagramResponse.from_row(row)
            for row in await container.semantic_view().list_diagrams(key)
        ]
        return dump([row.model_dump(mode="json") for row in rows])

    @mcp.resource(
        "semantic:///models/{model_id}/diagrams/{name}",
        name="model-diagram",
        description="One diagram of a model, or null when it does not exist.",
        mime_type="application/json",
    )
    async def model_diagram(model_id: str, name: str) -> str:
        """Return one diagram by name."""
        key = uuid_or_none(model_id)
        row = None if key is None else await container.semantic_view().get_diagram(key, name)
        return dump(None if row is None else DiagramResponse.from_row(row).model_dump(mode="json"))

    @mcp.resource(
        "semantic:///models/{model_id}/diagrams/{name}/nodes",
        name="diagram-nodes",
        description="The nodes of a diagram, ordered by entity name.",
        mime_type="application/json",
    )
    async def diagram_nodes(model_id: str, name: str) -> str:
        """Return the nodes of a diagram."""
        key = uuid_or_none(model_id)
        if key is None:
            return dump([])
        rows = [
            NodeResponse.from_row(row)
            for row in await container.semantic_view().list_nodes(key, name)
        ]
        return dump([row.model_dump(mode="json") for row in rows])
