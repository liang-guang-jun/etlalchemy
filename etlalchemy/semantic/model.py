"""Model container, query starters and merge entry point.

``SemanticRegistry`` holds the entities, relationships and measures of a model.
``SemanticModel`` is the addable unit exposed to callers; its ``q`` property
returns query starters bound to that model, so ``query.compile()`` works on the
result. The module-level ``q`` in ``etlalchemy.core.expression`` starts
unbound queries instead, which cannot be compiled until they are rebuilt from
``model.q``. Merge behavior is not implemented yet.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from etlalchemy.semantic.expression import Query
from etlalchemy.semantic.graph import GraphService
from etlalchemy.semantic.measure import Measure
from etlalchemy.semantic.relationship import (
    Cardinality,
    FilterDirection,
    SemanticRelationship,
    equi_join,
)
from etlalchemy.semantic.rowset import (
    FieldCollection,
    Rowset,
    SemanticEntity,
)

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

    def register_entity(self, name: str, relation: Rowset) -> SemanticEntity:
        """Register a Rowset under a name and return its entity.

        Args:
            name: Registry name of the entity; it is also the entity alias.
            relation: Rowset the entity reads from.

        Returns:
            The registered entity.

        Raises:
            ValueError: If ``name`` is already registered.
        """
        if name in self.registry.entities:
            raise ValueError(f"Entity {name!r} is already registered")
        entity = SemanticEntity(id=uuid4(), alias=name, relation=relation)
        self.registry.entities[name] = entity
        return entity

    def register_relationship(
        self,
        name: str,
        source: SemanticEntity,
        source_fields: Sequence[str],
        target: SemanticEntity,
        target_fields: Sequence[str],
        *,
        cardinality: Cardinality = Cardinality.ONE_TO_MANY,
        filter_direction: FilterDirection = FilterDirection.SINGLE,
        priority: int = 0,
    ) -> SemanticRelationship:
        """Register an equi-join between two entities of this model.

        The join keys are named, so callers do not build ``FieldCollection``
        objects themselves.

        Args:
            name: Registry name of the relationship.
            source: Entity the join starts from.
            source_fields: Column names of ``source``, aligned with
                ``target_fields``.
            target: Entity the join points at.
            target_fields: Column names of ``target``.
            cardinality: Data cardinality between the two ends.
            filter_direction: Whether filters propagate in one direction or
                both.
            priority: Selection priority among relationships of the same
                entity pair.

        Returns:
            The registered relationship.

        Raises:
            ValueError: If ``name`` is already registered, or if a named field
                is not in the rowset of its entity.
        """
        if any(item.name == name for item in self.registry.relationships):
            raise ValueError(f"Relationship {name!r} is already registered")
        relationship = equi_join(
            name=name,
            source=self._collection(source, source_fields),
            target=self._collection(target, target_fields),
            cardinality=cardinality,
            filter_direction=filter_direction,
            priority=priority,
        )
        self.registry.relationships.append(relationship)
        return relationship

    def register_measure(self, name: str, **kwargs: Any) -> Measure:
        """Register a Measure under a name.

        The keyword arguments are passed to :class:`~etlalchemy.semantic.Measure`
        unchanged.

        Args:
            name: Registry name of the measure.
            **kwargs: Fields of the measure, such as ``field``, ``fields``,
                ``entity``, ``aggregation`` and ``routes``.

        Returns:
            The registered measure.

        Raises:
            ValueError: If ``name`` is already registered.
        """
        if name in self.registry.measures:
            raise ValueError(f"Measure {name!r} is already registered")
        measure = Measure(name=name, **kwargs)
        self.registry.measures[name] = measure
        return measure

    @staticmethod
    def _collection(
        entity: SemanticEntity,
        names: Sequence[str],
    ) -> FieldCollection:
        """Return the fields of ``entity`` named by ``names``.

        Raises:
            ValueError: If a name is not a field of the entity's rowset.
        """
        fields = entity.relation.fields
        missing = [name for name in names if name not in fields]
        if missing:
            raise ValueError(
                f"Fields {missing} are not in the rowset of entity {entity.alias!r}"
            )
        return FieldCollection(
            entity=entity,
            fields=tuple(fields[name] for name in names),
        )

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
