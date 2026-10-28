"""Model container and merge entry point.

SemanticRegistry holds the entities and relationships of a model.
SemanticModel is the addable unit exposed to callers. Merge behavior is not
implemented yet.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import StrEnum

from etlalchemy.core.graph import GraphService
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

    def graph(
        self,
        relationships: Iterable[SemanticRelationship] | None = None,
    ) -> GraphService:
        """Build a GraphService over this model's entities and chosen edges.

        With no argument the full relationship set of :attr:`registry` is
        analysed, which is the worst-case check: an acyclic result proves that
        no per-pair priority selection can introduce a cycle. Callers can pass
        the result of ``highest_priority_edges``, ``edges_for_selection`` or
        ``edges_by_priority`` to analyse one specific selection instead.

        Labels come from the registry keys, so cycles are reported with the
        registered entity names. Entities missing from the registry keep the
        ``?``-prefixed alias assigned by ``GraphService``.

        The service is rebuilt on every call and is never cached on the model.

        Args:
            relationships: Explicit edge set to analyse; defaults to every
                relationship in the registry.

        Returns:
            A new ``GraphService`` for the requested edge set.
        """
        edges = (
            tuple(self.registry.relationships)
            if relationships is None
            else relationships
        )
        known_entities = {
            entity.id: name for name, entity in self.registry.entities.items()
        }
        return GraphService(edges, known_entities=known_entities)

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
