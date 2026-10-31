"""Model container, query starters and merge entry point.

``SemanticRegistry`` holds the entities, relationships and measures of a model.
``SemanticModel`` is the addable unit exposed to callers; its ``q`` property
returns query starters bound to that model, so ``query.compile()`` works on the
result. The module-level ``q`` in ``etlalchemy.core.expression`` starts
unbound queries instead, which cannot be compiled until they are rebuilt from
``model.q``. Merge behavior is not implemented yet.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING

from etlalchemy.semantic.expression import Query
from etlalchemy.semantic.graph import GraphService
from etlalchemy.semantic.measure import Measure
from etlalchemy.semantic.relationship import SemanticRelationship
from etlalchemy.semantic.rowset import SemanticEntity

if TYPE_CHECKING:
    from etlalchemy.diagram.diagram import Diagram


@dataclass
class SemanticRegistry:
    """Registry of a model's entities, relationships and measures.

    ``entities`` maps entity names to their definitions, ``relationships``
    holds the edges between them, and ``measures`` maps measure names to their
    definitions.
    """

    entities: dict[str, SemanticEntity] = field(default_factory=dict)
    relationships: list[SemanticRelationship] = field(default_factory=list)
    measures: dict[str, Measure] = field(default_factory=dict)


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
            entity.id: entity.alias for entity in self.registry.entities.values()
        }
        return GraphService(edges, known_entities=known_entities)

    def diagram(self, *entity_refs: str) -> Diagram:
        """Draw the named entities and the relationships between them.

        With no argument every entity is drawn. A relationship is drawn only
        when both of its ends are drawn, and a column is marked as joined only
        when a drawn relationship joins it.

        Args:
            entity_refs: Entity names, aliases or ids, in the order the boxes
                are to be read in. Duplicates are drawn once.

        Returns:
            The diagram of the selected entities.

        Raises:
            KeyError: If an entity reference matches no entity, or matches
                more than one entity.
        """
        from etlalchemy.diagram.service import DiagramService

        return DiagramService(self).build(*entity_refs)

    @property
    def q(self) -> _ModelQueryStarters:
        """Return query starters bound to this model.

        Queries started here carry ``model`` set to this model, so
        ``query.compile()`` can resolve entities and measures. The module-level
        ``q`` only builds model-independent queries.
        """
        return _ModelQueryStarters(self)

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


class _ModelQueryStarters:
    """Query starters bound to one model."""

    def __init__(self, model: SemanticModel) -> None:
        """Keep the model every started query is bound to."""
        self._model = model

    def group_by(
        self,
        *refs: str,
        alias: str | None = None,
        time_grain: str | None = None,
    ) -> Query:
        """Start a query on this model with the given dimensions."""
        return Query(model=self._model).group_by(
            *refs,
            alias=alias,
            time_grain=time_grain,
        )

    def calculate(self, measure: str, alias: str | None = None) -> Query:
        """Start a query on this model with the given measure."""
        return Query(model=self._model).calculate(measure, alias)

    def filter(self, *predicates: str) -> Query:
        """Start a query on this model with the given predicates."""
        return Query(model=self._model).filter(*predicates)

    def order_by(self, ref: str, descending: bool = False) -> Query:
        """Start a query on this model with the given ordering term."""
        return Query(model=self._model).order_by(ref, descending)

    def route(self, source: str, target: str, priority: int) -> Query:
        """Start a query on this model with a fixed route."""
        return Query(model=self._model).route(source, target, priority)

    def limit(self, n: int) -> Query:
        """Start a query on this model with a row limit."""
        return Query(model=self._model).limit(n)
