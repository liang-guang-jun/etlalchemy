"""Read model interface of the semantic context."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from uuid import UUID

from eventsourcing.asyncio.persistence import AsyncTrackingRecorder
from eventsourcing.persistence import Tracking

from etlalchemy.shared.utils import as_uuid as as_uuid

RefPair = tuple[str, str]
"""A ``(entity name, field name)`` reference of one relationship side."""


@dataclass(frozen=True)
class ModelRow:
    """A semantic model as stored in the read model."""

    model_id: UUID
    """ID of the model aggregate."""
    name: str
    """Name of the model."""
    description: str
    """Free-form description of the model."""


@dataclass(frozen=True)
class EntityRow:
    """A business entity backed by one catalog table."""

    model_id: UUID
    """ID of the model that owns the entity."""
    entity_id: UUID
    """Identity of the entity, stable across renames."""
    name: str
    """Name of the entity."""
    table_id: UUID
    """ID of the catalog table the entity maps to."""


@dataclass(frozen=True)
class RelationshipRow:
    """A field-level relation between two entities of one model."""

    relationship_id: UUID
    """ID of the relationship."""
    model_id: UUID
    """ID of the model that owns the relationship."""
    from_refs: list[RefPair]
    """``(entity, field)`` pairs of the ``from`` side."""
    to_refs: list[RefPair]
    """``(entity, field)`` pairs of the ``to`` side, paired by position."""
    cardinality: str
    """Cardinality of the relation."""
    filter_direction: str
    """Direction in which a filter flows across the relation."""
    priority: int
    """Sort hint, lower first."""


@dataclass(frozen=True)
class DiagramRow:
    """A canvas of one model."""

    model_id: UUID
    """ID of the model that owns the diagram."""
    name: str
    """Name of the diagram."""
    order: int
    """Sort hint, lower first."""


@dataclass(frozen=True)
class NodeRow:
    """One entity placed on a diagram canvas."""

    model_id: UUID
    """ID of the model that owns the diagram."""
    diagram_name: str
    """Name of the diagram."""
    entity_name: str
    """Name of the placed entity."""
    x: float
    """Horizontal position on the canvas."""
    y: float
    """Vertical position on the canvas."""


class SemanticView(AsyncTrackingRecorder, ABC):
    """Read model of the semantic context."""

    @abstractmethod
    async def create_table(self) -> None:
        """Creates the tracking table and the view tables if they do not exist."""

    # -- models -------------------------------------------------------------

    @abstractmethod
    async def register_model(
        self,
        model_id: UUID,
        name: str,
        description: str,
        tracking: Tracking,
    ) -> None:
        """Registers a model and its All diagram in one transaction."""

    @abstractmethod
    async def change_model(
        self,
        model_id: UUID,
        name: str | None,
        description: str | None,
        tracking: Tracking,
    ) -> None:
        """Changes the model, updating only the non-``None`` attributes."""

    @abstractmethod
    async def discard_model(self, model_id: UUID, tracking: Tracking) -> None:
        """Marks a model as discarded and deletes everything it owned."""

    @abstractmethod
    async def get_model(self, model_id: UUID) -> ModelRow | None:
        """Returns one live model, or ``None``."""

    @abstractmethod
    async def list_models(self) -> list[ModelRow]:
        """Returns every live model, ordered by name."""

    # -- entities -----------------------------------------------------------

    @abstractmethod
    async def register_entity(
        self,
        model_id: UUID,
        name: str,
        table_id: UUID,
        x: float,
        y: float,
        tracking: Tracking,
        entity_id: UUID | None = None,
    ) -> None:
        """Registers an entity and places its node on the All diagram."""

    @abstractmethod
    async def rename_entity(
        self,
        model_id: UUID,
        old_name: str,
        new_name: str,
        tracking: Tracking,
    ) -> None:
        """Renames an entity and rewrites the references and nodes that use it."""

    @abstractmethod
    async def change_entity_table(
        self,
        model_id: UUID,
        name: str,
        table_id: UUID,
        tracking: Tracking,
    ) -> None:
        """Points an entity at another catalog table in the view."""

    @abstractmethod
    async def remove_entity(self, model_id: UUID, name: str, tracking: Tracking) -> None:
        """Removes an entity, its relationships and the nodes that mention it."""

    @abstractmethod
    async def get_entity(self, model_id: UUID, name: str) -> EntityRow | None:
        """Returns one entity, or ``None``."""

    @abstractmethod
    async def list_entities(self, model_id: UUID) -> list[EntityRow]:
        """Returns the entities of a model, ordered by name."""

    @abstractmethod
    async def get_entity_by_id(self, entity_id: UUID) -> EntityRow | None:
        """Returns one entity addressed by its identity, or ``None``."""

    # -- relationships ------------------------------------------------------

    @abstractmethod
    async def register_relationship(
        self,
        relationship_id: UUID,
        model_id: UUID,
        from_refs: list[RefPair],
        to_refs: list[RefPair],
        cardinality: str,
        filter_direction: str,
        priority: int,
        tracking: Tracking,
    ) -> None:
        """Registers a relationship and its field references in the view."""

    @abstractmethod
    async def change_relationship(
        self,
        relationship_id: UUID,
        from_refs: list[RefPair] | None,
        to_refs: list[RefPair] | None,
        cardinality: str | None,
        filter_direction: str | None,
        priority: int | None,
        tracking: Tracking,
    ) -> None:
        """Changes a relationship, rewriting the given sides only."""

    @abstractmethod
    async def remove_relationship(self, relationship_id: UUID, tracking: Tracking) -> None:
        """Removes a relationship and its field references in the view."""

    @abstractmethod
    async def get_relationship(self, relationship_id: UUID) -> RelationshipRow | None:
        """Returns one relationship with its references, or ``None``."""

    @abstractmethod
    async def list_relationships(self, model_id: UUID) -> list[RelationshipRow]:
        """Returns the relationships of a model with their references."""

    # -- diagrams -----------------------------------------------------------

    @abstractmethod
    async def register_diagram(
        self,
        model_id: UUID,
        name: str,
        order: int,
        tracking: Tracking,
    ) -> None:
        """Registers a diagram in the view."""

    @abstractmethod
    async def rename_diagram(
        self,
        model_id: UUID,
        old_name: str,
        new_name: str,
        tracking: Tracking,
    ) -> None:
        """Renames a diagram and the nodes it owns."""

    @abstractmethod
    async def change_diagram_order(
        self,
        model_id: UUID,
        name: str,
        order: int,
        tracking: Tracking,
    ) -> None:
        """Changes the sort hint of a diagram."""

    @abstractmethod
    async def remove_diagram(self, model_id: UUID, name: str, tracking: Tracking) -> None:
        """Removes a diagram and its nodes."""

    @abstractmethod
    async def get_diagram(self, model_id: UUID, name: str) -> DiagramRow | None:
        """Returns one diagram, or ``None``."""

    @abstractmethod
    async def list_diagrams(self, model_id: UUID) -> list[DiagramRow]:
        """Returns the diagrams of a model, ordered by sort hint and name."""

    # -- nodes --------------------------------------------------------------

    @abstractmethod
    async def place_node(
        self,
        model_id: UUID,
        diagram_name: str,
        entity_name: str,
        x: float,
        y: float,
        tracking: Tracking,
    ) -> None:
        """Places an entity on a diagram in the view."""

    @abstractmethod
    async def move_node(
        self,
        model_id: UUID,
        diagram_name: str,
        entity_name: str,
        x: float,
        y: float,
        tracking: Tracking,
    ) -> None:
        """Moves a placed entity on a diagram in the view."""

    @abstractmethod
    async def remove_node(
        self,
        model_id: UUID,
        diagram_name: str,
        entity_name: str,
        tracking: Tracking,
    ) -> None:
        """Removes an entity from a diagram in the view."""

    @abstractmethod
    async def list_nodes(self, model_id: UUID, diagram_name: str) -> list[NodeRow]:
        """Returns the nodes of a diagram, ordered by entity name."""
