"""Model container, query starters and merge entry point.

``SemanticRegistry`` holds the entities, relationships and measures of a model.
``SemanticModel`` is the addable unit exposed to callers; its ``q`` property
returns query starters bound to that model, so ``query.compile()`` works on the
result. The module-level ``q`` in ``etlalchemy.core.expression`` starts
unbound queries instead, which cannot be compiled until they are rebuilt from
``model.q``. Merge behavior is not implemented yet.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING
from uuid import uuid4

from etlalchemy.semantic.expression import FieldRef, Query, RouteKey
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


class RegisteredEntity:
    """An entity bound with the fields picked for a join key.

    ``SemanticModel.__getitem__`` returns one, so a join key reads as
    ``model["orders"]["customer_id"]`` or
    ``model["orders"][["tenant_id", "customer_id"]]``.
    """

    def __init__(
        self,
        entity: SemanticEntity,
        selected_fields: Sequence[str] | None = None,
    ) -> None:
        """Bind ``entity`` with the fields picked so far."""
        self.entity = entity
        self.selected_fields: tuple[str, ...] = (
            tuple(selected_fields) if selected_fields else ()
        )

    @property
    def alias(self) -> str:
        """Return the alias of the bound entity."""
        return self.entity.alias

    def __getitem__(self, fields: str | Sequence[str]) -> RegisteredEntity:
        """Pick one field or several fields of the bound entity."""
        names = (fields,) if isinstance(fields, str) else tuple(fields)
        return RegisteredEntity(self.entity, names)

    def as_collection(self) -> FieldCollection:
        """Return the picked fields as a ``FieldCollection``.

        Raises:
            ValueError: If no field was picked, or a picked field is not in the
                rowset of the entity.
        """
        if not self.selected_fields:
            raise ValueError(
                f"Entity {self.entity.alias!r} has no fields selected; pick "
                "them with model['entity'][['field', ...]]"
            )
        fields = self.entity.relation.fields
        missing = [name for name in self.selected_fields if name not in fields]
        if missing:
            raise ValueError(
                f"Fields {missing} are not in the rowset of entity "
                f"{self.entity.alias!r}"
            )
        return FieldCollection(
            entity=self.entity,
            fields=tuple(fields[name] for name in self.selected_fields),
        )


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

    def __getitem__(self, name: str) -> RegisteredEntity:
        """Return a proxy for the entity registered under ``name``.

        The proxy picks join keys, so a relationship reads as
        ``model["orders"][["customer_id"]]``.

        Args:
            name: Registry name or alias of the entity.

        Returns:
            A proxy bound to the entity, with no fields picked yet.

        Raises:
            KeyError: If the model knows no entity by that name or alias.
        """
        entity = self.registry.entities.get(name)
        if entity is None:
            entity = next(
                (
                    item
                    for item in self.registry.entities.values()
                    if item.alias == name
                ),
                None,
            )
        if entity is None:
            raise KeyError(f"Entity {name!r} is not registered in the model")
        return RegisteredEntity(entity)

    def register_entity(self, name: str, relation: Rowset) -> SemanticEntity:
        """Register a Rowset under a name and return its entity.

        Registering the same name twice is idempotent: the entity registered
        first is returned.

        Args:
            name: Registry name of the entity; it is also the entity alias.
            relation: Rowset the entity reads from.

        Returns:
            The registered entity.
        """
        existing = self.registry.entities.get(name)
        if existing is not None:
            return existing
        entity = SemanticEntity(id=uuid4(), alias=name, relation=relation)
        self.registry.entities[name] = entity
        return entity

    def register_relationship(
        self,
        name: str,
        source: RegisteredEntity | SemanticEntity,
        target: RegisteredEntity | SemanticEntity,
        *,
        cardinality: Cardinality = Cardinality.ONE_TO_MANY,
        filter_direction: FilterDirection = FilterDirection.SINGLE,
        priority: int = 0,
    ) -> SemanticRelationship:
        """Register an equi-join between two entities of this model.

        The join keys travel with the operands, so they cannot disagree with
        each other:

            model.register_relationship(
                "orders_customers",
                source=model["orders"][["customer_id"]],
                target=model["customers"][["id"]],
            )

        Registering the same name twice is idempotent: the relationship
        registered first is returned.

        Args:
            name: Registry name of the relationship.
            source: Sliced entity carrying the source join fields.
            target: Sliced entity carrying the target join fields.
            cardinality: Data cardinality between the two ends.
            filter_direction: Whether filters propagate in one direction or
                both.
            priority: Selection priority among relationships of the same
                entity pair.

        Returns:
            The registered relationship.

        Raises:
            ValueError: If an operand is a bare entity, if no field was picked,
                or if a picked field is not in the rowset of its entity.
        """
        existing = next(
            (item for item in self.registry.relationships if item.name == name),
            None,
        )
        if existing is not None:
            return existing
        relationship = equi_join(
            name=name,
            source=_join_collection(name, source),
            target=_join_collection(name, target),
            cardinality=cardinality,
            filter_direction=filter_direction,
            priority=priority,
        )
        self.registry.relationships.append(relationship)
        return relationship

    def register_measure(
        self,
        name: str,
        field: FieldRef | None = None,
        fields: tuple[FieldRef, ...] = (),
        entity: str | None = None,
        aggregation: str = "sum",
        routes: Mapping[RouteKey, int] | None = None,
    ) -> Measure:
        """Register a Measure under a name.

        The arguments mirror :class:`~etlalchemy.semantic.Measure` exactly, so
        an editor completes them. Registering the same name twice is
        idempotent: the measure registered first is returned.

        Args:
            name: Registry name of the measure.
            field: Single column the aggregation is computed over.
            fields: Columns of a multi-column ``count_distinct``.
            entity: Fact entity of a ``COUNT(*)`` measure.
            aggregation: One of ``avg``, ``count``, ``count_distinct``,
                ``max``, ``min`` or ``sum``.
            routes: Default relationship priority per entity alias pair.

        Returns:
            The registered measure.
        """
        existing = self.registry.measures.get(name)
        if existing is not None:
            return existing
        measure = Measure(
            name=name,
            field=field,
            fields=fields,
            entity=entity,
            aggregation=aggregation,
            routes=routes or {},
        )
        self.registry.measures[name] = measure
        return measure

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


def _join_collection(
    relationship: str,
    item: RegisteredEntity | SemanticEntity,
) -> FieldCollection:
    """Return the join key of one side of a relationship.

    Raises:
        ValueError: If ``item`` is a bare entity instead of a sliced one, or if
            its picked fields are not in its rowset.
    """
    if isinstance(item, RegisteredEntity):
        return item.as_collection()
    raise ValueError(
        f"Relationship {relationship!r} requires the join keys to be picked "
        f"explicitly; pass model['{item.alias}'][['field']] instead of a bare "
        "entity"
    )
