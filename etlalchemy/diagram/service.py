"""Diagram construction service."""

from __future__ import annotations

from typing import TYPE_CHECKING

from etlalchemy.diagram.diagram import (
    Diagram,
    DiagramColumn,
    DiagramEdge,
    DiagramNode,
)
from etlalchemy.semantic.join import EquiJoin
from etlalchemy.semantic.rowset import Materialization

if TYPE_CHECKING:
    from uuid import UUID

    from etlalchemy.semantic.model import SemanticModel
    from etlalchemy.semantic.relationship import SemanticRelationship
    from etlalchemy.semantic.rowset import SemanticEntity

# The rowset kinds that stand for a physical relation, which is what a box is
# labelled with; a query or a CTE is not a table a reader can query directly.
_PHYSICAL: frozenset[Materialization] = frozenset(
    {Materialization.TABLE, Materialization.VIEW}
)


class DiagramService:
    """Select the entities and relationships a diagram draws."""

    def __init__(self, model: SemanticModel) -> None:
        """Store the model to draw.

        Args:
            model: Semantic model that owns entities and relationships.
        """
        self._model = model

    def build(self, *entity_refs: str) -> Diagram:
        """Build a diagram of the named entities, or of every entity.

        A relationship is drawn only when both of its ends are drawn, and a
        column is marked as joined only when a drawn relationship joins it, so
        that what a picture says about an entity is what the picture shows.

        Args:
            entity_refs: Entity names, aliases or ids, in the order the boxes
                are to be read in. Duplicates are drawn once. With no
                references, every entity is drawn in model declaration order.

        Returns:
            The diagram of the selected entities.

        Raises:
            KeyError: If an entity reference matches no entity, or matches
                more than one entity.
        """
        entities = self._select(entity_refs)
        drawn_ids = {entity.id for _, entity in entities}
        drawn: list[tuple[SemanticRelationship, SemanticEntity, SemanticEntity]] = []

        for relationship in self._model.registry.relationships:
            ends = self._ends(relationship)
            if ends is None:
                continue
            source, target = ends
            if source.id not in drawn_ids or target.id not in drawn_ids:
                continue
            drawn.append((relationship, source, target))

        joined = self._joined_columns(drawn)

        return Diagram(
            nodes=tuple(
                self._node_of(name, entity, joined.get(entity.id, frozenset()))
                for name, entity in entities
            ),
            edges=tuple(
                self._edge_of(relationship, source, target)
                for relationship, source, target in drawn
            ),
        )

    def _select(self, entity_refs: tuple[str, ...]) -> list[tuple[str, SemanticEntity]]:
        """Resolve the references into entities, in the order asked for."""
        registry = self._model.registry.entities

        if not entity_refs:
            return list(registry.items())

        entities: list[tuple[str, SemanticEntity]] = []
        seen: set[UUID] = set()

        for ref in entity_refs:
            name, entity = self._resolve(ref, registry)
            if entity.id in seen:
                continue
            seen.add(entity.id)
            entities.append((name, entity))

        return entities

    @staticmethod
    def _resolve(
        ref: str,
        registry: dict[str, SemanticEntity],
    ) -> tuple[str, SemanticEntity]:
        """Return the entity a name, an alias or an id refers to.

        Raises:
            KeyError: If no entity matches ``ref``, or if entities disagree on
                which one it names.
        """
        matches: dict[UUID, tuple[str, SemanticEntity]] = {}

        for name, entity in registry.items():
            if ref in (name, entity.alias) or str(entity.id) == ref:
                matches.setdefault(entity.id, (name, entity))

        if not matches:
            raise KeyError(f"Unknown entity reference: {ref!r}")
        if len(matches) > 1:
            raise KeyError(f"Entity reference {ref!r} matches more than one entity")

        return next(iter(matches.values()))

    def _ends(
        self,
        relationship: SemanticRelationship,
    ) -> tuple[SemanticEntity, SemanticEntity] | None:
        """Return the entities a relationship joins, when both are known."""
        condition = relationship.condition

        if isinstance(condition, EquiJoin):
            return condition.source.entity, condition.target.entity

        source_alias, target_alias = condition.referenced_entities()
        source = self._by_alias(source_alias)
        target = self._by_alias(target_alias)

        if source is None or target is None:
            return None

        return source, target

    def _by_alias(self, alias: str) -> SemanticEntity | None:
        """Return the registry entity with ``alias``, if there is one."""
        for entity in self._model.registry.entities.values():
            if entity.alias == alias:
                return entity

        return None

    @staticmethod
    def _joined_columns(
        drawn: list[tuple[SemanticRelationship, SemanticEntity, SemanticEntity]],
    ) -> dict[UUID, frozenset[str]]:
        """Return the columns each entity is joined on, by a drawn relationship."""
        joined: dict[UUID, set[str]] = {}

        for relationship, _, _ in drawn:
            condition = relationship.condition
            if not isinstance(condition, EquiJoin):
                continue
            for collection in (condition.source, condition.target):
                for field in collection.fields:
                    joined.setdefault(collection.entity.id, set()).add(field.name)

        return {entity_id: frozenset(names) for entity_id, names in joined.items()}

    @staticmethod
    def _node_of(
        name: str,
        entity: SemanticEntity,
        joined: frozenset[str],
    ) -> DiagramNode:
        """Return the box drawn for one entity."""
        rowset = entity.relation
        primary_key = set(rowset.primary_key or ())

        return DiagramNode(
            entity_id=str(entity.id),
            name=name,
            columns=tuple(
                DiagramColumn(
                    name=field.name,
                    data_type=field.data_type.to_string(),
                    is_primary_key=field.name in primary_key,
                    is_joined=field.name in joined,
                )
                for field in rowset.fields.values()
            ),
            table=rowset.name if rowset.kind in _PHYSICAL else None,
        )

    @staticmethod
    def _edge_of(
        relationship: SemanticRelationship,
        source: SemanticEntity,
        target: SemanticEntity,
    ) -> DiagramEdge:
        """Return the line drawn for one relationship."""
        condition = relationship.condition

        if isinstance(condition, EquiJoin):
            source_columns = tuple(field.name for field in condition.source.fields)
            target_columns = tuple(field.name for field in condition.target.fields)
        else:
            source_columns = ()
            target_columns = ()

        return DiagramEdge(
            relationship_id=relationship.name,
            name=relationship.name,
            source_entity_id=str(source.id),
            target_entity_id=str(target.id),
            source_columns=source_columns,
            target_columns=target_columns,
            cardinality=relationship.cardinality,
            direction=relationship.filter_direction,
            priority=relationship.priority,
        )
