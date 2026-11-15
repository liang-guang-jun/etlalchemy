"""Projection that materialises the semantic read model."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from eventsourcing.dispatch import singledispatchmethod
from eventsourcing.persistence import Tracking
from eventsourcing.utils import EnvType, get_topic

from etlalchemy._vendor.eventsourcing.asyncio.application import AsyncApplication
from etlalchemy._vendor.eventsourcing.asyncio.projection import AsyncProjectionRunner
from etlalchemy.semantic.aggregates.model import Model
from etlalchemy.semantic.projection.sqlalchemy import SQLAlchemySemanticView
from etlalchemy.semantic.projection.view import SemanticView
from etlalchemy.shared.logging import get_logger
from etlalchemy.shared.projection import AsyncLoggedProjection


class SemanticEventApplication(AsyncApplication[UUID]):
    """Application used by the projection runner to subscribe to semantic events.

    :class:`~etlalchemy.semantic.application.ModelApplication` needs the catalog
    read model, so the projection runner cannot construct it from an environment
    alone. This subclass carries the same application name (and therefore the same
    event store tables) without the use-case dependencies.
    """

    name = "semantic_application"
    """Application name; must match :class:`ModelApplication`."""


class SemanticProjection(AsyncLoggedProjection[SemanticView]):
    """Materialises the semantic read model from the semantic events.

    Every event carries the state the view needs, including the initial position
    of a node on the All diagram, so no handler has to read the view back.
    """

    name = "semantic_projection"
    """Projection name; used as the environment prefix and tracking table prefix."""

    logger_name = "semantic.projection"
    """Logger used for the per-event trail and for projection failures."""

    topics = (
        get_topic(Model.Started),
        get_topic(Model.Changed),
        get_topic(Model.Discarded),
        get_topic(Model.EntityAdded),
        get_topic(Model.EntityRenamed),
        get_topic(Model.EntityTableChanged),
        get_topic(Model.EntityRemoved),
        get_topic(Model.RelationshipAdded),
        get_topic(Model.RelationshipChanged),
        get_topic(Model.RelationshipRemoved),
        get_topic(Model.DiagramAdded),
        get_topic(Model.DiagramRenamed),
        get_topic(Model.DiagramOrderChanged),
        get_topic(Model.DiagramRemoved),
        get_topic(Model.NodePlaced),
        get_topic(Model.NodeMoved),
        get_topic(Model.NodeRemoved),
    )

    @singledispatchmethod
    async def dispatch_event(self, domain_event: Any, tracking: Tracking) -> None:
        """Ignores events that are not handled by this projection."""

    @dispatch_event.register
    async def _when_started(self, event: Model.Started, tracking: Tracking) -> None:
        """Registers the model and its implicit All diagram in the view."""
        await self.view.register_model(
            event.originator_id,
            event.name,
            event.description,
            tracking,
        )

    @dispatch_event.register
    async def _when_changed(self, event: Model.Changed, tracking: Tracking) -> None:
        """Changes the model in the view."""
        await self.view.change_model(
            event.originator_id,
            event.name,
            event.description,
            tracking,
        )

    @dispatch_event.register
    async def _when_discarded(self, event: Model.Discarded, tracking: Tracking) -> None:
        """Discards the model and everything it owned in the view."""
        await self.view.discard_model(event.originator_id, tracking)

    @dispatch_event.register
    async def _when_entity_added(self, event: Model.EntityAdded, tracking: Tracking) -> None:
        """Registers the entity and its node on the All diagram."""
        await self.view.register_entity(
            event.originator_id,
            event.entity_name,
            event.table_id,
            event.initial_x,
            event.initial_y,
            tracking,
            event.entity_id,
        )

    @dispatch_event.register
    async def _when_entity_renamed(self, event: Model.EntityRenamed, tracking: Tracking) -> None:
        """Renames the entity and rewrites the references and nodes that use it."""
        await self.view.rename_entity(
            event.originator_id,
            event.old_name,
            event.new_name,
            tracking,
        )

    @dispatch_event.register
    async def _when_entity_table_changed(
        self,
        event: Model.EntityTableChanged,
        tracking: Tracking,
    ) -> None:
        """Points the entity at its new catalog table."""
        await self.view.change_entity_table(
            event.originator_id,
            event.entity_name,
            event.table_id,
            tracking,
        )

    @dispatch_event.register
    async def _when_entity_removed(self, event: Model.EntityRemoved, tracking: Tracking) -> None:
        """Removes the entity together with what mentioned it."""
        await self.view.remove_entity(event.originator_id, event.entity_name, tracking)

    @dispatch_event.register
    async def _when_relationship_added(
        self,
        event: Model.RelationshipAdded,
        tracking: Tracking,
    ) -> None:
        """Registers the relationship and its field references."""
        await self.view.register_relationship(
            event.relationship_id,
            event.originator_id,
            list(event.from_refs),
            list(event.to_refs),
            event.cardinality,
            event.filter_direction,
            event.priority,
            tracking,
        )

    @dispatch_event.register
    async def _when_relationship_changed(
        self,
        event: Model.RelationshipChanged,
        tracking: Tracking,
    ) -> None:
        """Changes the given attributes and sides of a relationship."""
        await self.view.change_relationship(
            event.relationship_id,
            None if event.from_refs is None else list(event.from_refs),
            None if event.to_refs is None else list(event.to_refs),
            event.cardinality,
            event.filter_direction,
            event.priority,
            tracking,
        )

    @dispatch_event.register
    async def _when_relationship_removed(
        self,
        event: Model.RelationshipRemoved,
        tracking: Tracking,
    ) -> None:
        """Removes the relationship and its field references."""
        await self.view.remove_relationship(event.relationship_id, tracking)

    @dispatch_event.register
    async def _when_diagram_added(self, event: Model.DiagramAdded, tracking: Tracking) -> None:
        """Registers the diagram in the view."""
        await self.view.register_diagram(
            event.originator_id,
            event.name,
            event.order,
            tracking,
        )

    @dispatch_event.register
    async def _when_diagram_renamed(self, event: Model.DiagramRenamed, tracking: Tracking) -> None:
        """Renames the diagram and its nodes in the view."""
        await self.view.rename_diagram(
            event.originator_id,
            event.old_name,
            event.new_name,
            tracking,
        )

    @dispatch_event.register
    async def _when_diagram_order_changed(
        self,
        event: Model.DiagramOrderChanged,
        tracking: Tracking,
    ) -> None:
        """Changes the sort hint of the diagram in the view."""
        await self.view.change_diagram_order(
            event.originator_id,
            event.name,
            event.order,
            tracking,
        )

    @dispatch_event.register
    async def _when_diagram_removed(self, event: Model.DiagramRemoved, tracking: Tracking) -> None:
        """Removes the diagram and its nodes in the view."""
        await self.view.remove_diagram(event.originator_id, event.name, tracking)

    @dispatch_event.register
    async def _when_node_placed(self, event: Model.NodePlaced, tracking: Tracking) -> None:
        """Places the node on its diagram in the view."""
        await self.view.place_node(
            event.originator_id,
            event.diagram_name,
            event.entity_name,
            event.x,
            event.y,
            tracking,
        )

    @dispatch_event.register
    async def _when_node_moved(self, event: Model.NodeMoved, tracking: Tracking) -> None:
        """Moves the node on its diagram in the view."""
        await self.view.move_node(
            event.originator_id,
            event.diagram_name,
            event.entity_name,
            event.x,
            event.y,
            tracking,
        )

    @dispatch_event.register
    async def _when_node_removed(self, event: Model.NodeRemoved, tracking: Tracking) -> None:
        """Removes the node from its diagram in the view."""
        await self.view.remove_node(
            event.originator_id,
            event.diagram_name,
            event.entity_name,
            tracking,
        )


def run_semantic_projection(
    env: EnvType,
) -> AsyncProjectionRunner[SemanticEventApplication, SemanticView]:
    """Builds a runner that keeps the semantic view up to date.

    The runner is not started yet: the caller awaits ``start()`` (or uses the
    runner as an async context manager).
    """
    runner = AsyncProjectionRunner[SemanticEventApplication, SemanticView](
        application_class=SemanticEventApplication,
        projection_class=SemanticProjection,
        view_class=SQLAlchemySemanticView,
        env=env,
    )
    get_logger(SemanticProjection.logger_name).info(
        "projection.runner.started",
        application=SemanticEventApplication.name,
        projection=SemanticProjection.name,
        view=SQLAlchemySemanticView.__name__,
    )
    return runner
