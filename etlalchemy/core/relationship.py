"""Relationship edges between FieldCollections."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from etlalchemy.core.rowset import FieldCollection


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
    """Relationship edge between two FieldCollections with composite keys."""

    name: str
    source: FieldCollection
    target: FieldCollection
    cardinality: Cardinality = Cardinality.ONE_TO_MANY
    filter_direction: FilterDirection = FilterDirection.SINGLE
    priority: int = 0

    def __post_init__(self) -> None:
        """Validate that both sides of a composite key have the same length."""
        if len(self.source.fields) != len(self.target.fields):
            raise ValueError(
                f"Composite key length mismatch: source={len(self.source.fields)} "
                f"target={len(self.target.fields)}"
            )
