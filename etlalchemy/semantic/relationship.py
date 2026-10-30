"""Relationship edges between two semantic entities.

A relationship holds a ``JoinCondition`` instead of a fixed pair of
``FieldCollection`` objects. ``EquiJoin`` keeps the original column-by-column
equality behaviour, while ``ExpressionJoin`` allows an expression predicate.
``source`` and ``target`` are convenience properties that are only available
when the condition is an ``EquiJoin``; use ``source_alias()`` and
``target_alias()`` when the relationship may be an expression join. The
``equi_join`` and ``expression_join`` factories keep construction concise and
backward compatible.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from etlalchemy.semantic.join import EquiJoin, ExpressionJoin, JoinCondition
from etlalchemy.semantic.rowset import FieldCollection


class Cardinality(StrEnum):
    """Data cardinality between the two ends of a Relationship."""

    ONE_TO_MANY = "ONE_TO_MANY"
    ONE_TO_ONE = "ONE_TO_ONE"
    MANY_TO_MANY = "MANY_TO_MANY"


class FilterDirection(StrEnum):
    """Propagation direction of filters along a Relationship."""

    SINGLE = "SINGLE"
    BOTH = "BOTH"


@dataclass
class SemanticRelationship:
    """Relationship edge between two entities, described by a JoinCondition.

    ``condition`` is any :class:`~etlalchemy.semantic.join.JoinCondition`. The
    ``source`` and ``target`` properties expose the underlying
    ``FieldCollection`` objects only for ``EquiJoin`` conditions and raise
    ``AttributeError`` for expression joins; ``source_alias()`` and
    ``target_alias()`` work for every condition.
    """

    name: str
    condition: JoinCondition
    cardinality: Cardinality = Cardinality.ONE_TO_MANY
    filter_direction: FilterDirection = FilterDirection.SINGLE
    priority: int = 0

    def __post_init__(self) -> None:
        """Validate that the condition implements the JoinCondition protocol."""
        if not isinstance(self.condition, JoinCondition):
            raise TypeError("condition must implement JoinCondition")

    @property
    def source(self) -> FieldCollection:
        """Return the source FieldCollection when the condition is an EquiJoin."""
        if isinstance(self.condition, EquiJoin):
            return self.condition.source
        raise AttributeError("ExpressionJoin has no source FieldCollection")

    @property
    def target(self) -> FieldCollection:
        """Return the target FieldCollection when the condition is an EquiJoin."""
        if isinstance(self.condition, EquiJoin):
            return self.condition.target
        raise AttributeError("ExpressionJoin has no target FieldCollection")

    def source_alias(self) -> str:
        """Return the source entity alias."""
        return self.condition.source_entity_alias()

    def target_alias(self) -> str:
        """Return the target entity alias."""
        return self.condition.target_entity_alias()


def equi_join(
    name: str,
    source: FieldCollection,
    target: FieldCollection,
    cardinality: Cardinality = Cardinality.ONE_TO_MANY,
    filter_direction: FilterDirection = FilterDirection.SINGLE,
    priority: int = 0,
) -> SemanticRelationship:
    """Build a SemanticRelationship with an EquiJoin condition."""
    return SemanticRelationship(
        name=name,
        condition=EquiJoin(source=source, target=target),
        cardinality=cardinality,
        filter_direction=filter_direction,
        priority=priority,
    )


def expression_join(
    name: str,
    source_entity: str,
    target_entity: str,
    expression: str,
    cardinality: Cardinality = Cardinality.ONE_TO_MANY,
    filter_direction: FilterDirection = FilterDirection.SINGLE,
    priority: int = 0,
) -> SemanticRelationship:
    """Build a SemanticRelationship with an ExpressionJoin condition."""
    return SemanticRelationship(
        name=name,
        condition=ExpressionJoin(
            source_entity=source_entity,
            target_entity=target_entity,
            expression=expression,
        ),
        cardinality=cardinality,
        filter_direction=filter_direction,
        priority=priority,
    )
