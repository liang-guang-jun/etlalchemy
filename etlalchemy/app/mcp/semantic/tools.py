"""Semantic context MCP tools."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastmcp import FastMCP
from pydantic import BaseModel, Field

from etlalchemy.app.bootstrap import Container
from etlalchemy.app.mcp.errors import mcp_error_guard
from etlalchemy.app.schemas.common import OkResponse
from etlalchemy.app.schemas.semantic import (
    DiagramResponse,
    EntityResponse,
    ModelCreatedResponse,
    ModelResponse,
    NodeResponse,
    RelationshipCreatedResponse,
    RelationshipResponse,
)
from etlalchemy.semantic.aggregates.types import Cardinality, FieldRef, FilterDirection


class FieldRefArg(BaseModel):
    """One ``entity.field`` reference of a relationship side."""

    entity: str
    """Name of the entity that owns the field."""
    field: str
    """Name of the field."""

    def to_ref(self) -> FieldRef:
        """Returns the value object the application expects."""
        return FieldRef(entity=self.entity, field=self.field)


ALL_HINT = (
    "The 'All' diagram always shows every entity: its nodes cannot be placed or removed, "
    "but they can be moved."
)
"""Description shared by the node tools."""


def register(mcp: FastMCP, container: Container) -> None:
    """Registers the semantic tools on the given server."""
    # ---- model -----------------------------------------------------------

    @mcp.tool(
        name="create_model",
        description="Create a semantic model and return the id of the new aggregate.",
    )
    async def create_model(
        name: Annotated[str, Field(description="Name of the new model.")],
        description: Annotated[
            str,
            Field(description="Free-form description of the model."),
        ] = "",
    ) -> ModelCreatedResponse:
        """Create a model."""
        with mcp_error_guard():
            model_id = await container.semantic_application().create_model(
                name,
                description,
            )
        return ModelCreatedResponse(model_id=model_id)

    @mcp.tool(
        name="change_model",
        description="Change the name and/or description of a semantic model.",
    )
    async def change_model(
        model_id: Annotated[UUID, Field(description="ID of the model.")],
        name: Annotated[
            str | None,
            Field(description="New name, or null to keep the current one."),
        ] = None,
        description: Annotated[
            str | None,
            Field(description="New description, or null to keep the current one."),
        ] = None,
    ) -> OkResponse:
        """Change a model."""
        with mcp_error_guard():
            await container.semantic_application().change_model(model_id, name, description)
        return OkResponse()

    @mcp.tool(
        name="discard_model",
        description="Discard a model together with its entities, relationships and diagrams.",
        annotations={"destructiveHint": True},
    )
    async def discard_model(
        model_id: Annotated[UUID, Field(description="ID of the model to discard.")],
    ) -> OkResponse:
        """Discard a model."""
        with mcp_error_guard():
            await container.semantic_application().discard_model(model_id)
        return OkResponse()

    # ---- entities --------------------------------------------------------

    @mcp.tool(
        name="add_entity",
        description=(
            "Add an entity backed by a catalog table. The entity name is its identity "
            "inside the model."
        ),
    )
    async def add_entity(
        model_id: Annotated[UUID, Field(description="ID of the model.")],
        entity_name: Annotated[str, Field(description="Name of the new entity.")],
        table_id: Annotated[UUID, Field(description="ID of the catalog table to map.")],
    ) -> EntityResponse:
        """Add an entity."""
        with mcp_error_guard():
            await container.semantic_application().add_entity(model_id, entity_name, table_id)
        return EntityResponse(model_id=model_id, name=entity_name, table_id=table_id)

    @mcp.tool(
        name="rename_entity",
        description=(
            "Rename an entity. Relationships and diagram nodes that reference the old "
            "name follow the rename."
        ),
    )
    async def rename_entity(
        model_id: Annotated[UUID, Field(description="ID of the model.")],
        old_name: Annotated[str, Field(description="Current entity name.")],
        new_name: Annotated[str, Field(description="New entity name.")],
    ) -> OkResponse:
        """Rename an entity."""
        with mcp_error_guard():
            await container.semantic_application().rename_entity(model_id, old_name, new_name)
        return OkResponse()

    @mcp.tool(
        name="change_entity_table",
        description=(
            "Point an entity at another catalog table. This is rejected while a "
            "relationship references the entity."
        ),
    )
    async def change_entity_table(
        model_id: Annotated[UUID, Field(description="ID of the model.")],
        entity_name: Annotated[str, Field(description="Name of the entity.")],
        table_id: Annotated[UUID, Field(description="ID of the new catalog table.")],
    ) -> OkResponse:
        """Change the table of an entity."""
        with mcp_error_guard():
            await container.semantic_application().change_entity_table(
                model_id,
                entity_name,
                table_id,
            )
        return OkResponse()

    @mcp.tool(
        name="remove_entity",
        description=(
            "Remove an entity. Every relationship and diagram node that references it "
            "is removed too."
        ),
        annotations={"destructiveHint": True},
    )
    async def remove_entity(
        model_id: Annotated[UUID, Field(description="ID of the model.")],
        entity_name: Annotated[str, Field(description="Name of the entity to remove.")],
    ) -> OkResponse:
        """Remove an entity."""
        with mcp_error_guard():
            await container.semantic_application().remove_entity(model_id, entity_name)
        return OkResponse()

    # ---- relationships ---------------------------------------------------

    @mcp.tool(
        name="add_relationship",
        description=(
            "Add a field-level relationship. from_refs and to_refs must have the same "
            "length and pair up item by item; every entity must exist in the model and "
            "every field must exist in that entity's catalog table."
        ),
    )
    async def add_relationship(
        model_id: Annotated[UUID, Field(description="ID of the model.")],
        from_refs: Annotated[list[FieldRefArg], Field(description="'from' references.")],
        to_refs: Annotated[list[FieldRefArg], Field(description="'to' references.")],
        cardinality: Annotated[
            Cardinality,
            Field(description="one_to_many, one_to_one or many_to_many."),
        ],
        filter_direction: Annotated[
            FilterDirection,
            Field(description="single or both."),
        ] = FilterDirection.SINGLE,
        priority: Annotated[int, Field(description="Sort hint, lower first.")] = 0,
    ) -> RelationshipCreatedResponse:
        """Add a relationship."""
        with mcp_error_guard():
            relationship_id = await container.semantic_application().add_relationship(
                model_id,
                [ref.to_ref() for ref in from_refs],
                [ref.to_ref() for ref in to_refs],
                cardinality,
                filter_direction,
                priority,
            )
        return RelationshipCreatedResponse(relationship_id=relationship_id)

    @mcp.tool(
        name="change_relationship",
        description="Change the given attributes of a relationship.",
    )
    async def change_relationship(
        model_id: Annotated[UUID, Field(description="ID of the model.")],
        relationship_id: Annotated[UUID, Field(description="ID of the relationship.")],
        from_refs: Annotated[
            list[FieldRefArg] | None,
            Field(description="New 'from' references, or null to keep the current ones."),
        ] = None,
        to_refs: Annotated[
            list[FieldRefArg] | None,
            Field(description="New 'to' references, or null to keep the current ones."),
        ] = None,
        cardinality: Annotated[
            Cardinality | None,
            Field(description="New cardinality, or null to keep the current one."),
        ] = None,
        filter_direction: Annotated[
            FilterDirection | None,
            Field(description="New filter direction, or null to keep the current one."),
        ] = None,
        priority: Annotated[
            int | None,
            Field(description="New sort hint, or null to keep the current one."),
        ] = None,
    ) -> OkResponse:
        """Change a relationship."""
        with mcp_error_guard():
            await container.semantic_application().change_relationship(
                model_id,
                relationship_id,
                None if from_refs is None else [ref.to_ref() for ref in from_refs],
                None if to_refs is None else [ref.to_ref() for ref in to_refs],
                cardinality,
                filter_direction,
                priority,
            )
        return OkResponse()

    @mcp.tool(
        name="remove_relationship",
        description="Remove a relationship from a model.",
        annotations={"destructiveHint": True},
    )
    async def remove_relationship(
        model_id: Annotated[UUID, Field(description="ID of the model.")],
        relationship_id: Annotated[UUID, Field(description="ID of the relationship.")],
    ) -> OkResponse:
        """Remove a relationship."""
        with mcp_error_guard():
            await container.semantic_application().remove_relationship(
                model_id,
                relationship_id,
            )
        return OkResponse()

    # ---- diagrams --------------------------------------------------------

    @mcp.tool(
        name="add_diagram",
        description="Add an empty diagram to a model and return it.",
    )
    async def add_diagram(
        model_id: Annotated[UUID, Field(description="ID of the model.")],
        name: Annotated[str, Field(description="Name of the new diagram.")],
        order: Annotated[int, Field(description="Sort hint, lower first.")] = 0,
    ) -> DiagramResponse:
        """Add a diagram."""
        with mcp_error_guard():
            await container.semantic_application().add_diagram(model_id, name, order)
        return DiagramResponse(model_id=model_id, name=name, order=order)

    @mcp.tool(
        name="rename_diagram",
        description="Rename a diagram, keeping its nodes. The All diagram cannot be renamed.",
    )
    async def rename_diagram(
        model_id: Annotated[UUID, Field(description="ID of the model.")],
        old_name: Annotated[str, Field(description="Current diagram name.")],
        new_name: Annotated[str, Field(description="New diagram name.")],
    ) -> OkResponse:
        """Rename a diagram."""
        with mcp_error_guard():
            await container.semantic_application().rename_diagram(model_id, old_name, new_name)
        return OkResponse()

    @mcp.tool(
        name="change_diagram_order",
        description="Change the sort hint of a diagram, the All diagram included.",
    )
    async def change_diagram_order(
        model_id: Annotated[UUID, Field(description="ID of the model.")],
        name: Annotated[str, Field(description="Name of the diagram.")],
        order: Annotated[int, Field(description="New sort hint.")],
    ) -> OkResponse:
        """Change the order of a diagram."""
        with mcp_error_guard():
            await container.semantic_application().change_diagram_order(model_id, name, order)
        return OkResponse()

    @mcp.tool(
        name="remove_diagram",
        description="Remove a diagram and its nodes. The All diagram cannot be removed.",
        annotations={"destructiveHint": True},
    )
    async def remove_diagram(
        model_id: Annotated[UUID, Field(description="ID of the model.")],
        name: Annotated[str, Field(description="Name of the diagram to remove.")],
    ) -> OkResponse:
        """Remove a diagram."""
        with mcp_error_guard():
            await container.semantic_application().remove_diagram(model_id, name)
        return OkResponse()

    # ---- nodes -----------------------------------------------------------

    @mcp.tool(
        name="place_node",
        description=("Place an entity on a diagram. " + ALL_HINT),
    )
    async def place_node(
        model_id: Annotated[UUID, Field(description="ID of the model.")],
        diagram_name: Annotated[str, Field(description="Name of the diagram.")],
        entity_name: Annotated[str, Field(description="Name of the entity to place.")],
        x: Annotated[float, Field(description="Horizontal position on the canvas.")],
        y: Annotated[float, Field(description="Vertical position on the canvas.")],
    ) -> NodeResponse:
        """Place a node."""
        with mcp_error_guard():
            await container.semantic_application().place_node(
                model_id,
                diagram_name,
                entity_name,
                x,
                y,
            )
        return NodeResponse(
            model_id=model_id,
            diagram_name=diagram_name,
            entity_name=entity_name,
            x=x,
            y=y,
        )

    @mcp.tool(
        name="move_node",
        description=("Move a placed entity on a diagram, the All diagram included. " + ALL_HINT),
    )
    async def move_node(
        model_id: Annotated[UUID, Field(description="ID of the model.")],
        diagram_name: Annotated[str, Field(description="Name of the diagram.")],
        entity_name: Annotated[str, Field(description="Name of the placed entity.")],
        x: Annotated[float, Field(description="New horizontal position.")],
        y: Annotated[float, Field(description="New vertical position.")],
    ) -> OkResponse:
        """Move a node."""
        with mcp_error_guard():
            await container.semantic_application().move_node(
                model_id,
                diagram_name,
                entity_name,
                x,
                y,
            )
        return OkResponse()

    @mcp.tool(
        name="remove_node",
        description=("Remove an entity from a diagram. " + ALL_HINT),
        annotations={"destructiveHint": True},
    )
    async def remove_node(
        model_id: Annotated[UUID, Field(description="ID of the model.")],
        diagram_name: Annotated[str, Field(description="Name of the diagram.")],
        entity_name: Annotated[str, Field(description="Name of the entity to remove.")],
    ) -> OkResponse:
        """Remove a node."""
        with mcp_error_guard():
            await container.semantic_application().remove_node(
                model_id,
                diagram_name,
                entity_name,
            )
        return OkResponse()

    # ---- reads -----------------------------------------------------------

    @mcp.tool(
        name="list_models",
        description="List all live semantic models, ordered by name.",
        annotations={"readOnlyHint": True},
    )
    async def list_models() -> list[ModelResponse]:
        """List models."""
        rows = await container.semantic_view().list_models()
        return [ModelResponse.from_row(row) for row in rows]

    @mcp.tool(
        name="get_model",
        description="Return one live model, or null when it does not exist.",
        annotations={"readOnlyHint": True},
    )
    async def get_model(
        model_id: Annotated[UUID, Field(description="ID of the model.")],
    ) -> ModelResponse | None:
        """Get a model."""
        row = await container.semantic_view().get_model(model_id)
        return None if row is None else ModelResponse.from_row(row)

    @mcp.tool(
        name="list_entities",
        description="List the entities of a model, ordered by name.",
        annotations={"readOnlyHint": True},
    )
    async def list_entities(
        model_id: Annotated[UUID, Field(description="ID of the model.")],
    ) -> list[EntityResponse]:
        """List entities."""
        rows = await container.semantic_view().list_entities(model_id)
        return [EntityResponse.from_row(row) for row in rows]

    @mcp.tool(
        name="get_entity",
        description="Return one entity of a model, or null when it does not exist.",
        annotations={"readOnlyHint": True},
    )
    async def get_entity(
        model_id: Annotated[UUID, Field(description="ID of the model.")],
        entity_name: Annotated[str, Field(description="Name of the entity.")],
    ) -> EntityResponse | None:
        """Get an entity."""
        row = await container.semantic_view().get_entity(model_id, entity_name)
        return None if row is None else EntityResponse.from_row(row)

    @mcp.tool(
        name="list_relationships",
        description="List the relationships of a model with both of their sides.",
        annotations={"readOnlyHint": True},
    )
    async def list_relationships(
        model_id: Annotated[UUID, Field(description="ID of the model.")],
    ) -> list[RelationshipResponse]:
        """List relationships."""
        rows = await container.semantic_view().list_relationships(model_id)
        return [RelationshipResponse.from_row(row) for row in rows]

    @mcp.tool(
        name="get_relationship",
        description=("Return one relationship of a model, or null when it does not exist in it."),
        annotations={"readOnlyHint": True},
    )
    async def get_relationship(
        model_id: Annotated[UUID, Field(description="ID of the model.")],
        relationship_id: Annotated[UUID, Field(description="ID of the relationship.")],
    ) -> RelationshipResponse | None:
        """Get a relationship."""
        row = await container.semantic_view().get_relationship(relationship_id)
        if row is None or row.model_id != model_id:
            return None
        return RelationshipResponse.from_row(row)

    @mcp.tool(
        name="list_diagrams",
        description="List the diagrams of a model, ordered by sort hint and name.",
        annotations={"readOnlyHint": True},
    )
    async def list_diagrams(
        model_id: Annotated[UUID, Field(description="ID of the model.")],
    ) -> list[DiagramResponse]:
        """List diagrams."""
        rows = await container.semantic_view().list_diagrams(model_id)
        return [DiagramResponse.from_row(row) for row in rows]

    @mcp.tool(
        name="get_diagram",
        description="Return one diagram of a model, or null when it does not exist.",
        annotations={"readOnlyHint": True},
    )
    async def get_diagram(
        model_id: Annotated[UUID, Field(description="ID of the model.")],
        name: Annotated[str, Field(description="Name of the diagram.")],
    ) -> DiagramResponse | None:
        """Get a diagram."""
        row = await container.semantic_view().get_diagram(model_id, name)
        return None if row is None else DiagramResponse.from_row(row)

    @mcp.tool(
        name="list_nodes",
        description="List the nodes of a diagram, ordered by entity name.",
        annotations={"readOnlyHint": True},
    )
    async def list_nodes(
        model_id: Annotated[UUID, Field(description="ID of the model.")],
        diagram_name: Annotated[str, Field(description="Name of the diagram.")],
    ) -> list[NodeResponse]:
        """List nodes."""
        rows = await container.semantic_view().list_nodes(model_id, diagram_name)
        return [NodeResponse.from_row(row) for row in rows]
