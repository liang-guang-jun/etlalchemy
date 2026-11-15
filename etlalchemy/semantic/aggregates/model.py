"""Model aggregate: the semantic model, its entities, relationships and canvases."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from uuid import NAMESPACE_URL, UUID, uuid5

from eventsourcing.domain import Aggregate, AggregateCreated, event

from etlalchemy.semantic.aggregates.errors import (
    DiscardedError,
    DuplicateDiagramError,
    DuplicateEntityError,
    DuplicateNodeError,
    DuplicateRelationshipError,
    EntityInUseError,
    InvalidDiagramError,
    InvalidEntityNameError,
    InvalidRelationshipError,
    UnknownDiagramError,
    UnknownEntityError,
    UnknownNodeError,
    UnknownRelationshipError,
)
from etlalchemy.semantic.aggregates.types import (
    ALL_DIAGRAM,
    Cardinality,
    Diagram,
    Entity,
    FilterDirection,
    Node,
    Relationship,
)

ENTITY_NAMESPACE = uuid5(NAMESPACE_URL, "etlalchemy/semantic/entity")
"""Namespace of the entity identities, so they stay stable across replays."""

DIAGONAL_STEP = 40.0
"""Distance between two automatically placed nodes of the All diagram."""


def entity_identity(model_id: UUID, name: str) -> UUID:
    """Returns the identity of an entity inside its model.

    Entities are registered by name, so events written before entities carried
    an identity replay without one; this derivation keeps their id stable
    instead of inventing a new random one on every replay.
    """
    return uuid5(ENTITY_NAMESPACE, f"{model_id}:{name}")


Refs = tuple[tuple[str, str], ...]
"""Field references of one relationship side, as stored in the aggregate."""


def _normalise_refs(refs: Iterable[Sequence[str]]) -> Refs:
    """Returns the given references as ``(entity, field)`` tuples."""
    return tuple((str(entity), str(field)) for entity, field in refs)


def _renamed_refs(refs: Refs, old_name: str, new_name: str) -> Refs:
    """Returns the references with one entity name replaced."""
    return tuple(
        (new_name, field_name) if entity == old_name else (entity, field_name)
        for entity, field_name in refs
    )


def _mentions(relationship: Relationship, entity_name: str) -> bool:
    """Returns whether the relationship references the given entity."""
    sides = (relationship.from_refs, relationship.to_refs)
    return any(entity == entity_name for refs in sides for entity, _ in refs)


def _validate_entity_name(entity_name: str) -> None:
    """Rejects a blank entity name or one containing a path separator."""
    if not entity_name.strip():
        msg = "an entity name must not be blank"
        raise InvalidEntityNameError(msg)
    if "/" in entity_name:
        msg = f"entity name {entity_name!r} must not contain '/'"
        raise InvalidEntityNameError(msg)


def _validate_diagram_name(diagram_name: str) -> None:
    """Rejects a blank or reserved diagram name, or one containing ``/``."""
    if not diagram_name.strip():
        msg = "a diagram name must not be blank"
        raise InvalidDiagramError(msg)
    if "/" in diagram_name:
        msg = f"diagram name {diagram_name!r} must not contain '/'"
        raise InvalidDiagramError(msg)
    if diagram_name == ALL_DIAGRAM:
        msg = f"diagram name {ALL_DIAGRAM!r} is reserved"
        raise InvalidDiagramError(msg)


def _cardinality(value: Cardinality | str) -> str:
    """Returns the canonical name of a cardinality, rejecting unknown values."""
    try:
        return Cardinality(value).value
    except ValueError as exc:
        msg = f"unknown cardinality {value!r}"
        raise InvalidRelationshipError(msg) from exc


def _filter_direction(value: FilterDirection | str) -> str:
    """Returns the canonical name of a filter direction, rejecting unknown values."""
    try:
        return FilterDirection(value).value
    except ValueError as exc:
        msg = f"unknown filter direction {value!r}"
        raise InvalidRelationshipError(msg) from exc


class Model(Aggregate):
    """Aggregate root that owns the semantic model of one data catalog.

    Entities, relationships, diagrams and their nodes are internal entities, so
    the cross-cutting invariants hold inside one unit of work: a relationship
    only references existing entities, removing an entity drops what mentions it,
    and the ``All`` diagram always shows exactly the entities of the model.
    """

    def __init__(self, name: str, description: str = "") -> None:
        """Initialises a model with the given name, description and All diagram."""
        self.name = name
        self.description = description
        self.entities: dict[str, Entity] = {}
        self.relationships: dict[UUID, Relationship] = {}
        self.diagrams: dict[str, Diagram] = {ALL_DIAGRAM: Diagram(name=ALL_DIAGRAM)}
        self._is_discarded = False

    class Event(Aggregate.Event):
        """Base class for events raised by the model aggregate."""

    @dataclass(frozen=True)
    class Started(AggregateCreated):
        """Recorded when a model is created."""

        name: str
        """Name of the new model."""
        description: str = ""
        """Free-form description of the new model."""

    @dataclass(frozen=True)
    class Changed(Event):
        """Recorded when the model name or description changes."""

        name: str | None = None
        """New name, or ``None`` when unchanged."""
        description: str | None = None
        """New description, or ``None`` when unchanged."""

    @dataclass(frozen=True)
    class Discarded(Event):
        """Recorded when the model is discarded."""

    @dataclass(frozen=True)
    class EntityAdded(Event):
        """Recorded when an entity is added to the model."""

        entity_name: str
        """Name of the new entity."""
        table_id: UUID
        """ID of the catalog table the entity maps to."""
        initial_x: float = 0.0
        """Horizontal position of the node added to the All diagram."""
        initial_y: float = 0.0
        """Vertical position of the node added to the All diagram."""
        entity_id: UUID | None = None
        """Identity of the entity, or ``None`` for events written before it existed."""

    @dataclass(frozen=True)
    class EntityRenamed(Event):
        """Recorded when an entity is renamed."""

        old_name: str
        """Name the entity had before the rename."""
        new_name: str
        """Name the entity has after the rename."""

    @dataclass(frozen=True)
    class EntityTableChanged(Event):
        """Recorded when an entity is pointed at another catalog table."""

        entity_name: str
        """Name of the entity."""
        table_id: UUID
        """ID of the new catalog table."""

    @dataclass(frozen=True)
    class EntityRemoved(Event):
        """Recorded when an entity is removed from the model."""

        entity_name: str
        """Name of the removed entity."""

    @dataclass(frozen=True)
    class RelationshipAdded(Event):
        """Recorded when a relationship is added to the model."""

        relationship_id: UUID
        """ID of the new relationship."""
        from_refs: Refs
        """``(entity, field)`` pairs of the ``from`` side."""
        to_refs: Refs
        """``(entity, field)`` pairs of the ``to`` side."""
        cardinality: str
        """Cardinality of the relation, one of :class:`Cardinality`."""
        filter_direction: str
        """Filter direction, one of :class:`FilterDirection`."""
        priority: int = 0
        """Sort hint, lower first."""

        def __post_init__(self) -> None:
            """Normalises decoded JSON lists into reference tuples."""
            object.__setattr__(self, "from_refs", _normalise_refs(self.from_refs))
            object.__setattr__(self, "to_refs", _normalise_refs(self.to_refs))

    @dataclass(frozen=True)
    class RelationshipChanged(Event):
        """Recorded when one or more attributes of a relationship change."""

        relationship_id: UUID
        """ID of the changed relationship."""
        from_refs: Refs | None = None
        """New ``from`` references, or ``None`` when unchanged."""
        to_refs: Refs | None = None
        """New ``to`` references, or ``None`` when unchanged."""
        cardinality: str | None = None
        """New cardinality, or ``None`` when unchanged."""
        filter_direction: str | None = None
        """New filter direction, or ``None`` when unchanged."""
        priority: int | None = None
        """New sort hint, or ``None`` when unchanged."""

        def __post_init__(self) -> None:
            """Normalises decoded JSON lists into reference tuples."""
            if self.from_refs is not None:
                object.__setattr__(self, "from_refs", _normalise_refs(self.from_refs))
            if self.to_refs is not None:
                object.__setattr__(self, "to_refs", _normalise_refs(self.to_refs))

    @dataclass(frozen=True)
    class RelationshipRemoved(Event):
        """Recorded when a relationship is removed from the model."""

        relationship_id: UUID
        """ID of the removed relationship."""

    @dataclass(frozen=True)
    class DiagramAdded(Event):
        """Recorded when a diagram is added to the model."""

        name: str
        """Name of the new diagram."""
        order: int = 0
        """Sort hint, lower first."""

    @dataclass(frozen=True)
    class DiagramRenamed(Event):
        """Recorded when a diagram is renamed."""

        old_name: str
        """Name the diagram had before the rename."""
        new_name: str
        """Name the diagram has after the rename."""

    @dataclass(frozen=True)
    class DiagramOrderChanged(Event):
        """Recorded when the sort hint of a diagram changes."""

        name: str
        """Name of the diagram."""
        order: int
        """New sort hint."""

    @dataclass(frozen=True)
    class DiagramRemoved(Event):
        """Recorded when a diagram is removed from the model."""

        name: str
        """Name of the removed diagram."""

    @dataclass(frozen=True)
    class NodePlaced(Event):
        """Recorded when an entity is placed on a diagram."""

        diagram_name: str
        """Name of the diagram."""
        entity_name: str
        """Name of the placed entity."""
        x: float
        """Horizontal position on the canvas."""
        y: float
        """Vertical position on the canvas."""

    @dataclass(frozen=True)
    class NodeMoved(Event):
        """Recorded when a placed entity moves on a diagram."""

        diagram_name: str
        """Name of the diagram."""
        entity_name: str
        """Name of the moved entity."""
        x: float
        """New horizontal position on the canvas."""
        y: float
        """New vertical position on the canvas."""

    @dataclass(frozen=True)
    class NodeRemoved(Event):
        """Recorded when an entity is removed from a diagram."""

        diagram_name: str
        """Name of the diagram."""
        entity_name: str
        """Name of the removed entity."""

    # -- model --------------------------------------------------------------

    @event(Changed)
    def change(self, name: str | None = None, description: str | None = None) -> None:
        """Changes the model name and/or description."""
        self._ensure_not_discarded()
        if name is None and description is None:
            msg = "change() requires a new name or description"
            raise ValueError(msg)
        if name is not None:
            self.name = name
        if description is not None:
            self.description = description

    @event(Discarded)
    def discard(self) -> None:
        """Marks the model as discarded."""
        self._ensure_not_discarded()
        self._is_discarded = True

    # -- entities -----------------------------------------------------------

    def add_entity(
        self,
        entity_name: str,
        table_id: UUID,
        entity_id: UUID | None = None,
    ) -> None:
        """Adds an entity and places its node on the All diagram."""
        self._ensure_not_discarded()
        _validate_entity_name(entity_name)
        if entity_name in self.entities:
            msg = f"entity {entity_name!r} already exists in model {self.name!r}"
            raise DuplicateEntityError(msg)
        index = len(self.diagrams[ALL_DIAGRAM].nodes)
        offset = index * DIAGONAL_STEP
        self._entity_added(entity_name, table_id, offset, offset, entity_id)

    def rename_entity(self, old_name: str, new_name: str) -> None:
        """Renames an entity and rewrites every reference to it."""
        self._ensure_not_discarded()
        self._require_entity(old_name)
        _validate_entity_name(new_name)
        if new_name == old_name:
            return
        if new_name in self.entities:
            msg = f"entity {new_name!r} already exists in model {self.name!r}"
            raise DuplicateEntityError(msg)
        self._entity_renamed(old_name, new_name)

    def change_entity_table(self, entity_name: str, table_id: UUID) -> None:
        """Points an entity at another catalog table."""
        self._ensure_not_discarded()
        self._require_entity(entity_name)
        referencing = [rel for rel in self.relationships.values() if _mentions(rel, entity_name)]
        if referencing:
            msg = (
                f"entity {entity_name!r} is referenced by "
                f"{len(referencing)} relationship(s) in model {self.name!r}"
            )
            raise EntityInUseError(msg)
        self._entity_table_changed(entity_name, table_id)

    def remove_entity(self, entity_name: str) -> None:
        """Removes an entity together with every relationship and node using it."""
        self._ensure_not_discarded()
        self._require_entity(entity_name)
        self._entity_removed(entity_name)

    # -- relationships ------------------------------------------------------

    def add_relationship(
        self,
        relationship_id: UUID,
        from_refs: Refs,
        to_refs: Refs,
        cardinality: Cardinality,
        filter_direction: FilterDirection,
        priority: int = 0,
    ) -> None:
        """Adds a relationship between fields of two existing entities."""
        self._ensure_not_discarded()
        if relationship_id in self.relationships:
            msg = f"relationship {relationship_id} already exists in model {self.name!r}"
            raise DuplicateRelationshipError(msg)
        self._validate_refs(from_refs, to_refs)
        self._relationship_added(
            relationship_id,
            from_refs,
            to_refs,
            _cardinality(cardinality),
            _filter_direction(filter_direction),
            priority,
        )

    def change_relationship(
        self,
        relationship_id: UUID,
        from_refs: Refs | None = None,
        to_refs: Refs | None = None,
        cardinality: Cardinality | None = None,
        filter_direction: FilterDirection | None = None,
        priority: int | None = None,
    ) -> None:
        """Changes the given attributes of an existing relationship."""
        self._ensure_not_discarded()
        relationship = self._require_relationship(relationship_id)
        if all(
            value is None for value in (from_refs, to_refs, cardinality, filter_direction, priority)
        ):
            msg = "change_relationship() requires at least one new attribute"
            raise ValueError(msg)
        new_from = relationship.from_refs if from_refs is None else _normalise_refs(from_refs)
        new_to = relationship.to_refs if to_refs is None else _normalise_refs(to_refs)
        self._validate_refs(new_from, new_to)
        self._relationship_changed(
            relationship_id,
            from_refs,
            to_refs,
            None if cardinality is None else _cardinality(cardinality),
            None if filter_direction is None else _filter_direction(filter_direction),
            priority,
        )

    def remove_relationship(self, relationship_id: UUID) -> None:
        """Removes a relationship from the model."""
        self._ensure_not_discarded()
        self._require_relationship(relationship_id)
        self._relationship_removed(relationship_id)

    # -- diagrams -----------------------------------------------------------

    def add_diagram(self, name: str, order: int = 0) -> None:
        """Adds an empty diagram to the model."""
        self._ensure_not_discarded()
        _validate_diagram_name(name)
        if name in self.diagrams:
            msg = f"diagram {name!r} already exists in model {self.name!r}"
            raise DuplicateDiagramError(msg)
        self._diagram_added(name, order)

    def rename_diagram(self, old_name: str, new_name: str) -> None:
        """Renames a diagram, keeping its nodes."""
        self._ensure_not_discarded()
        if old_name == ALL_DIAGRAM:
            msg = f"diagram {ALL_DIAGRAM!r} cannot be renamed"
            raise InvalidDiagramError(msg)
        self._require_diagram(old_name)
        _validate_diagram_name(new_name)
        if new_name == old_name:
            return
        if new_name in self.diagrams:
            msg = f"diagram {new_name!r} already exists in model {self.name!r}"
            raise DuplicateDiagramError(msg)
        self._diagram_renamed(old_name, new_name)

    def change_diagram_order(self, name: str, order: int) -> None:
        """Changes the sort hint of a diagram, the All diagram included."""
        self._ensure_not_discarded()
        diagram = self._require_diagram(name)
        if diagram.order == order:
            return
        self._diagram_order_changed(name, order)

    def remove_diagram(self, name: str) -> None:
        """Removes a diagram and the nodes it owned."""
        self._ensure_not_discarded()
        if name == ALL_DIAGRAM:
            msg = f"diagram {ALL_DIAGRAM!r} cannot be removed"
            raise InvalidDiagramError(msg)
        self._require_diagram(name)
        self._diagram_removed(name)

    # -- nodes --------------------------------------------------------------

    def place_node(self, diagram_name: str, entity_name: str, x: float, y: float) -> None:
        """Places an entity on a diagram that manages its nodes manually."""
        self._ensure_not_discarded()
        if diagram_name == ALL_DIAGRAM:
            msg = f"diagram {ALL_DIAGRAM!r} manages its nodes automatically"
            raise InvalidDiagramError(msg)
        diagram = self._require_diagram(diagram_name)
        self._require_entity(entity_name)
        if entity_name in diagram.nodes:
            msg = f"entity {entity_name!r} is already placed on diagram {diagram_name!r}"
            raise DuplicateNodeError(msg)
        self._node_placed(diagram_name, entity_name, x, y)

    def move_node(self, diagram_name: str, entity_name: str, x: float, y: float) -> None:
        """Moves a placed node, the All diagram included."""
        self._ensure_not_discarded()
        diagram = self._require_diagram(diagram_name)
        node = diagram.nodes.get(entity_name)
        if node is None:
            msg = f"diagram {diagram_name!r} has no node for entity {entity_name!r}"
            raise UnknownNodeError(msg)
        if (node.x, node.y) == (x, y):
            return
        self._node_moved(diagram_name, entity_name, x, y)

    def remove_node(self, diagram_name: str, entity_name: str) -> None:
        """Removes a node from a diagram that manages its nodes manually."""
        self._ensure_not_discarded()
        if diagram_name == ALL_DIAGRAM:
            msg = f"diagram {ALL_DIAGRAM!r} manages its nodes automatically"
            raise InvalidDiagramError(msg)
        diagram = self._require_diagram(diagram_name)
        if entity_name not in diagram.nodes:
            msg = f"diagram {diagram_name!r} has no node for entity {entity_name!r}"
            raise UnknownNodeError(msg)
        self._node_removed(diagram_name, entity_name)

    # -- internal apply -----------------------------------------------------

    @event(EntityAdded)
    def _entity_added(
        self,
        entity_name: str,
        table_id: UUID,
        initial_x: float,
        initial_y: float,
        entity_id: UUID | None = None,
    ) -> None:
        """Records the new entity and its node on the All diagram."""
        self.entities[entity_name] = Entity(
            entity_id=entity_id or entity_identity(self.id, entity_name),
            name=entity_name,
            table_id=table_id,
        )
        self.diagrams[ALL_DIAGRAM].nodes[entity_name] = Node(
            entity=entity_name,
            x=initial_x,
            y=initial_y,
        )

    @event(EntityRenamed)
    def _entity_renamed(self, old_name: str, new_name: str) -> None:
        """Records the rename and rewrites every reference and node key."""
        entity = self.entities.pop(old_name)
        entity.name = new_name
        self.entities[new_name] = entity
        for relationship in self.relationships.values():
            relationship.from_refs = _renamed_refs(relationship.from_refs, old_name, new_name)
            relationship.to_refs = _renamed_refs(relationship.to_refs, old_name, new_name)
        for diagram in self.diagrams.values():
            node = diagram.nodes.pop(old_name, None)
            if node is not None:
                node.entity = new_name
                diagram.nodes[new_name] = node

    @event(EntityTableChanged)
    def _entity_table_changed(self, entity_name: str, table_id: UUID) -> None:
        """Records the new table of an entity."""
        self.entities[entity_name].table_id = table_id

    @event(EntityRemoved)
    def _entity_removed(self, entity_name: str) -> None:
        """Records the removal and drops every relationship and node using it."""
        del self.entities[entity_name]
        self.relationships = {
            relationship_id: relationship
            for relationship_id, relationship in self.relationships.items()
            if not _mentions(relationship, entity_name)
        }
        for diagram in self.diagrams.values():
            diagram.nodes.pop(entity_name, None)

    @event(RelationshipAdded)
    def _relationship_added(
        self,
        relationship_id: UUID,
        from_refs: Refs,
        to_refs: Refs,
        cardinality: str,
        filter_direction: str,
        priority: int = 0,
    ) -> None:
        """Records the new relationship."""
        self.relationships[relationship_id] = Relationship(
            id=relationship_id,
            from_refs=_normalise_refs(from_refs),
            to_refs=_normalise_refs(to_refs),
            cardinality=Cardinality(cardinality),
            filter_direction=FilterDirection(filter_direction),
            priority=priority,
        )

    @event(RelationshipChanged)
    def _relationship_changed(
        self,
        relationship_id: UUID,
        from_refs: Refs | None = None,
        to_refs: Refs | None = None,
        cardinality: str | None = None,
        filter_direction: str | None = None,
        priority: int | None = None,
    ) -> None:
        """Records the new attributes of a relationship."""
        relationship = self.relationships[relationship_id]
        if from_refs is not None:
            relationship.from_refs = _normalise_refs(from_refs)
        if to_refs is not None:
            relationship.to_refs = _normalise_refs(to_refs)
        if cardinality is not None:
            relationship.cardinality = Cardinality(cardinality)
        if filter_direction is not None:
            relationship.filter_direction = FilterDirection(filter_direction)
        if priority is not None:
            relationship.priority = priority

    @event(RelationshipRemoved)
    def _relationship_removed(self, relationship_id: UUID) -> None:
        """Records the removal of a relationship."""
        del self.relationships[relationship_id]

    @event(DiagramAdded)
    def _diagram_added(self, name: str, order: int = 0) -> None:
        """Records the new diagram."""
        self.diagrams[name] = Diagram(name=name, order=order)

    @event(DiagramRenamed)
    def _diagram_renamed(self, old_name: str, new_name: str) -> None:
        """Records the rename, keeping the nodes of the diagram."""
        diagram = self.diagrams.pop(old_name)
        diagram.name = new_name
        self.diagrams[new_name] = diagram

    @event(DiagramOrderChanged)
    def _diagram_order_changed(self, name: str, order: int) -> None:
        """Records the new sort hint of a diagram."""
        self.diagrams[name].order = order

    @event(DiagramRemoved)
    def _diagram_removed(self, name: str) -> None:
        """Records the removal of a diagram and its nodes."""
        del self.diagrams[name]

    @event(NodePlaced)
    def _node_placed(self, diagram_name: str, entity_name: str, x: float, y: float) -> None:
        """Records the placement of a node."""
        self.diagrams[diagram_name].nodes[entity_name] = Node(entity=entity_name, x=x, y=y)

    @event(NodeMoved)
    def _node_moved(self, diagram_name: str, entity_name: str, x: float, y: float) -> None:
        """Records the new position of a node."""
        node = self.diagrams[diagram_name].nodes[entity_name]
        node.x = x
        node.y = y

    @event(NodeRemoved)
    def _node_removed(self, diagram_name: str, entity_name: str) -> None:
        """Records the removal of a node."""
        del self.diagrams[diagram_name].nodes[entity_name]

    # -- helpers ------------------------------------------------------------

    def _validate_refs(self, from_refs: Refs, to_refs: Refs) -> None:
        """Rejects refs that are empty, unpaired or reference unknown entities."""
        if not from_refs or not to_refs:
            msg = "a relationship requires at least one field reference on each side"
            raise InvalidRelationshipError(msg)
        if len(from_refs) != len(to_refs):
            msg = (
                f"from_refs and to_refs must pair up, got {len(from_refs)} "
                f"and {len(to_refs)} references"
            )
            raise InvalidRelationshipError(msg)
        for entity_name, field_name in (*from_refs, *to_refs):
            if not field_name.strip():
                msg = f"a field reference of entity {entity_name!r} requires a field name"
                raise InvalidRelationshipError(msg)
            if entity_name not in self.entities:
                msg = f"entity {entity_name!r} does not exist in model {self.name!r}"
                raise InvalidRelationshipError(msg)

    def _require_entity(self, entity_name: str) -> Entity:
        """Returns the entity with the given name."""
        try:
            return self.entities[entity_name]
        except KeyError:
            msg = f"entity {entity_name!r} does not exist in model {self.name!r}"
            raise UnknownEntityError(msg) from None

    def _require_relationship(self, relationship_id: UUID) -> Relationship:
        """Returns the relationship with the given id."""
        try:
            return self.relationships[relationship_id]
        except KeyError:
            msg = f"relationship {relationship_id} does not exist in model {self.name!r}"
            raise UnknownRelationshipError(msg) from None

    def _require_diagram(self, name: str) -> Diagram:
        """Returns the diagram with the given name."""
        try:
            return self.diagrams[name]
        except KeyError:
            msg = f"diagram {name!r} does not exist in model {self.name!r}"
            raise UnknownDiagramError(msg) from None

    def _ensure_not_discarded(self) -> None:
        """Raises DiscardedError when the model has been discarded."""
        if self._is_discarded:
            msg = "model is discarded"
            raise DiscardedError(msg)
