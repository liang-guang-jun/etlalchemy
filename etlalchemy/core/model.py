"""Model container and merge entry point.

SemanticRegistry holds the entities and relationships of a model.
SemanticModel is the addable unit exposed to callers. Merge behavior is not
implemented yet.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from etlalchemy.core.relationship import SemanticRelationship
from etlalchemy.core.rowset import SemanticEntity


@dataclass
class SemanticRegistry:
    """Registry of entities and relationships."""

    entities: dict[str, SemanticEntity] = field(default_factory=dict)
    relationships: list[SemanticRelationship] = field(default_factory=list)


class MergeStrategy(StrEnum):
    """Conflict resolution strategy when merging two SemanticModels."""

    ERROR = "error"
    OVERRIDE = "override"
    KEEP_LEFT = "keep_left"


@dataclass
class SemanticModel:
    """Addable semantic model unit that holds a Registry."""

    name: str
    registry: SemanticRegistry = field(default_factory=SemanticRegistry)

    def __add__(self, other: SemanticModel) -> SemanticModel:
        """Merge two models; behavior is not implemented yet."""
        raise NotImplementedError

    def merge(
        self,
        other: SemanticModel,
        strategy: MergeStrategy = MergeStrategy.ERROR,
    ) -> SemanticModel:
        """Merge two models with the given strategy; behavior is not implemented yet."""
        raise NotImplementedError
