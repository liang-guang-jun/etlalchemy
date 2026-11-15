"""Response models of the semantic context."""

from __future__ import annotations

from typing import Self
from uuid import UUID

from pydantic import BaseModel

from etlalchemy.semantic.projection.view import (
    DiagramRow,
    EntityRow,
    ModelRow,
    NodeRow,
    RelationshipRow,
)


class ModelResponse(BaseModel):
    """A semantic model as exposed by the delivery layers."""

    model_id: UUID
    """ID of the model aggregate."""
    name: str
    """Name of the model."""
    description: str
    """Free-form description of the model."""

    @classmethod
    def from_row(cls, row: ModelRow) -> Self:
        """Builds the model from a read model row."""
        return cls(model_id=row.model_id, name=row.name, description=row.description)


class EntityResponse(BaseModel):
    """A business entity backed by one catalog table."""

    model_id: UUID
    """ID of the model that owns the entity."""
    entity_id: UUID | None = None
    """Identity of the entity, stable across renames and usable as a comment target."""
    name: str
    """Name of the entity."""
    table_id: UUID
    """ID of the catalog table the entity maps to."""

    @classmethod
    def from_row(cls, row: EntityRow) -> Self:
        """Builds the model from a read model row."""
        return cls(
            model_id=row.model_id,
            entity_id=row.entity_id,
            name=row.name,
            table_id=row.table_id,
        )


class FieldRefResponse(BaseModel):
    """One ``entity.field`` reference of a relationship side."""

    entity: str
    """Name of the entity that owns the field."""
    field: str
    """Name of the field."""


class RelationshipResponse(BaseModel):
    """A field-level relation between two entities of one model."""

    relationship_id: UUID
    """ID of the relationship."""
    model_id: UUID
    """ID of the model that owns the relationship."""
    from_refs: list[FieldRefResponse]
    """``from`` references, paired with ``to_refs`` by position."""
    to_refs: list[FieldRefResponse]
    """``to`` references, paired with ``from_refs`` by position."""
    cardinality: str
    """Cardinality of the relation."""
    filter_direction: str
    """Direction in which a filter flows across the relation."""
    priority: int
    """Sort hint, lower first."""

    @classmethod
    def from_row(cls, row: RelationshipRow) -> Self:
        """Builds the model from a read model row."""
        return cls(
            relationship_id=row.relationship_id,
            model_id=row.model_id,
            from_refs=[
                FieldRefResponse(entity=entity, field=field) for entity, field in row.from_refs
            ],
            to_refs=[FieldRefResponse(entity=entity, field=field) for entity, field in row.to_refs],
            cardinality=row.cardinality,
            filter_direction=row.filter_direction,
            priority=row.priority,
        )


class DiagramResponse(BaseModel):
    """A canvas of one model."""

    model_id: UUID
    """ID of the model that owns the diagram."""
    name: str
    """Name of the diagram."""
    order: int
    """Sort hint, lower first."""

    @classmethod
    def from_row(cls, row: DiagramRow) -> Self:
        """Builds the model from a read model row."""
        return cls(model_id=row.model_id, name=row.name, order=row.order)


class NodeResponse(BaseModel):
    """One entity placed on a diagram canvas."""

    model_id: UUID
    """ID of the model that owns the diagram."""
    diagram_name: str
    """Name of the diagram."""
    entity_name: str
    """Name of the placed entity."""
    x: float
    """Horizontal position on the canvas."""
    y: float
    """Vertical position on the canvas."""

    @classmethod
    def from_row(cls, row: NodeRow) -> Self:
        """Builds the model from a read model row."""
        return cls(
            model_id=row.model_id,
            diagram_name=row.diagram_name,
            entity_name=row.entity_name,
            x=row.x,
            y=row.y,
        )


class ModelCreatedResponse(BaseModel):
    """Result of ``create_model``."""

    model_id: UUID
    """ID of the new model."""


class RelationshipCreatedResponse(BaseModel):
    """Result of ``add_relationship``."""

    relationship_id: UUID
    """ID of the new relationship."""
