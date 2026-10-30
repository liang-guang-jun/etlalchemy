"""Relationship edges between two semantic entities.

A relationship holds a ``JoinCondition`` instead of a fixed pair of
``FieldCollection`` objects. ``EquiJoin`` keeps the original column-by-column
equality behaviour, while ``ExpressionJoin`` allows an expression predicate.
``source`` and ``target`` are convenience properties that are only available
when the condition is an ``EquiJoin``; use ``is_equi_join()`` when the caller
needs to branch on the kind, and ``source_alias()`` and ``target_alias()`` when
the relationship may be an expression join.

Build relationships with the ``equi_join`` and ``expression_join`` factories:
the constructor only takes a ``condition`` object, so the former
``source=``/``target=`` keywords are gone. The ``condition`` argument is typed
as ``JoinCondition`` and checked by mypy; there is no runtime ``isinstance``
check because a runtime-checkable ``Protocol`` only compares method names and
would accept objects whose signatures are wrong.
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

    ``condition`` is any :class:`~etlalchemy.semantic.join.JoinCondition`; the
    type checker validates it when the relationship is built and a condition
    that lacks a method fails when that method is called. The ``source`` and
    ``target`` properties expose the underlying ``FieldCollection`` objects
    only for ``EquiJoin`` conditions and raise ``AttributeError`` for expression
    joins; ``source_alias()`` and ``target_alias()`` work for every condition
    and ``is_equi_join()`` states the kind explicitly, so callers do not have
    to probe the properties with ``hasattr``.
    """

    name: str
    condition: JoinCondition
    cardinality: Cardinality = Cardinality.ONE_TO_MANY
    filter_direction: FilterDirection = FilterDirection.SINGLE
    priority: int = 0

    def __post_init__(self) -> None:
        """Reject expression joins that would need bidirectional filters.

        Raises:
            ValueError: If an ``ExpressionJoin`` asks for
                ``filter_direction=BOTH``, which the first version does not
                support; the error surfaces at construction instead of during
                compilation.
        """
        if (
            isinstance(self.condition, ExpressionJoin)
            and self.filter_direction is FilterDirection.BOTH
        ):
            raise ValueError(
                "expression joins only support filter_direction='SINGLE' in the "
                "first version"
            )

    def is_equi_join(self) -> bool:
        """Return whether the condition is an ``EquiJoin``."""
        return isinstance(self.condition, EquiJoin)

    @property
    def source(self) -> FieldCollection:
        """Return the source FieldCollection when the condition is an EquiJoin."""
        if isinstance(self.condition, EquiJoin):
            return self.condition.source
        raise AttributeError(
            f"{type(self.condition).__name__} has no source FieldCollection"
        )

    @property
    def target(self) -> FieldCollection:
        """Return the target FieldCollection when the condition is an EquiJoin."""
        if isinstance(self.condition, EquiJoin):
            return self.condition.target
        raise AttributeError(
            f"{type(self.condition).__name__} has no target FieldCollection"
        )

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
    """Build a SemanticRelationship with an EquiJoin condition.

    Args:
        name: Relationship name, unique within a registry.
        source: Fields of the source entity that form the join key.
        target: Fields of the target entity, aligned with ``source`` column by
            column; both sides must have the same number of fields.
        cardinality: Data cardinality between the two ends.
        filter_direction: Whether filters propagate along the edge in one
            direction or both.
        priority: Selection priority among relationships of the same entity
            pair; the highest priority wins by default.
    """
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
    """Build a SemanticRelationship with an ExpressionJoin condition.

    Args:
        name: Relationship name, unique within a registry.
        source_entity: Alias of the source entity.
        target_entity: Alias of the target entity; it may equal
            ``source_entity`` for a self join.
        expression: SQL predicate using the ``{source}`` and ``{target}``
            placeholders for the rendered table aliases. Format specifiers,
            conversions and malformed braces are rejected.
        cardinality: Data cardinality between the two ends.
        filter_direction: Filters only propagate in one direction in the first
            version, so ``BOTH`` is rejected.
        priority: Selection priority among relationships of the same entity
            pair; the highest priority wins by default.

    Raises:
        ValueError: If the expression has unsupported or malformed placeholders,
            or if ``filter_direction`` is ``BOTH``.
    """
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


__all__ = [
    "Cardinality",
    "FilterDirection",
    "SemanticRelationship",
    "equi_join",
    "expression_join",
]
