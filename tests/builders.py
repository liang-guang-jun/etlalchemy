"""Builders shared by the core test modules."""

from __future__ import annotations

from uuid import UUID, uuid5

from etlalchemy.semantic import (
    Cardinality,
    Field,
    FieldCollection,
    Materialization,
    Rowset,
    SemanticEntity,
    SemanticRelationship,
    String,
    equi_join,
)

NAMESPACE = UUID("00000000-0000-0000-0000-000000000000")


def entity(name: str, *, id_text: str | None = None) -> SemanticEntity:
    """Build a single-column entity named after its rowset."""
    fields = {"id": Field(name="id", data_type=String())}
    rowset = Rowset(name=name, kind=Materialization.TABLE, fields=fields)
    return SemanticEntity(
        id=uuid5(NAMESPACE, id_text or name), alias=name, relation=rowset
    )


def relationship(
    name: str,
    source: SemanticEntity,
    target: SemanticEntity,
    *,
    cardinality: Cardinality = Cardinality.ONE_TO_MANY,
    priority: int = 0,
) -> SemanticRelationship:
    """Build a single-column relationship between two entities."""
    return equi_join(
        name=name,
        source=FieldCollection(source, (source.relation.fields["id"],)),
        target=FieldCollection(target, (target.relation.fields["id"],)),
        cardinality=cardinality,
        priority=priority,
    )


def known(*entities: SemanticEntity) -> dict[UUID, str]:
    """Map entity ids to their display labels for GraphService."""
    return {item.id: item.alias for item in entities}
