"""Projection that materialises the catalog read model."""

from __future__ import annotations

from typing import Any

from eventsourcing.asyncio.projection import AsyncProjectionRunner
from eventsourcing.dispatch import singledispatchmethod
from eventsourcing.persistence import Tracking
from eventsourcing.utils import EnvType, get_topic

from etlalchemy.catalog.aggregates.catalog import Catalog
from etlalchemy.catalog.aggregates.schema import Schema
from etlalchemy.catalog.aggregates.table import Table
from etlalchemy.catalog.application import CatalogApplication
from etlalchemy.catalog.projection.sqlalchemy import SQLAlchemyCatalogView
from etlalchemy.catalog.projection.view import CatalogView
from etlalchemy.shared.logging import get_logger
from etlalchemy.shared.projection import AsyncLoggedProjection


class CatalogProjectionError(RuntimeError):
    """Raised when the view cannot be updated from an application event."""


class CatalogProjection(AsyncLoggedProjection[CatalogView]):
    """Materialises the catalog read model from the catalog events.

    The projection subscribes to the events that change the catalog structure and
    delegates each one to the corresponding command of the materialised view.
    """

    name = "catalog_projection"
    """Projection name; used as the environment prefix and tracking table prefix."""

    logger_name = "catalog.projection"
    """Logger used for the per-event trail and for projection failures."""

    topics = (
        get_topic(Catalog.Started),
        get_topic(Catalog.SchemaRegistered),
        get_topic(Catalog.SchemaUnregistered),
        get_topic(Catalog.Changed),
        get_topic(Catalog.Discarded),
        get_topic(Catalog.SchemaNameChanged),
        get_topic(Schema.TableRegistered),
        get_topic(Schema.TableUnregistered),
        get_topic(Schema.Changed),
        get_topic(Schema.Discarded),
        get_topic(Schema.TableNameChanged),
        get_topic(Table.FieldAdded),
        get_topic(Table.FieldRemoved),
        get_topic(Table.FieldTypeChanged),
        get_topic(Table.FieldNullabilityChanged),
        get_topic(Table.FieldCommentChanged),
        get_topic(Table.Changed),
        get_topic(Table.Discarded),
        get_topic(Table.FieldRenamed),
    )

    @singledispatchmethod
    async def dispatch_event(self, domain_event: Any, tracking: Tracking) -> None:
        """Ignores events that are not handled by this projection."""

    @dispatch_event.register
    async def _when_catalog_started(
        self,
        event: Catalog.Started,
        tracking: Tracking,
    ) -> None:
        """Registers the catalog in the view."""
        await self.view.register_catalog(
            event.originator_id,
            event.name,
            event.description,
            tracking,
        )

    @dispatch_event.register
    async def _when_schema_registered(
        self,
        event: Catalog.SchemaRegistered,
        tracking: Tracking,
    ) -> None:
        """Registers the schema in the view."""
        await self.view.register_schema(
            event.schema_id,
            event.originator_id,
            event.schema_name,
            event.description,
            tracking,
        )

    @dispatch_event.register
    async def _when_schema_unregistered(
        self,
        event: Catalog.SchemaUnregistered,
        tracking: Tracking,
    ) -> None:
        """Unregisters the schema from the view."""
        await self.view.unregister_schema(
            event.originator_id,
            event.schema_name,
            tracking,
        )

    @dispatch_event.register
    async def _when_table_registered(
        self,
        event: Schema.TableRegistered,
        tracking: Tracking,
    ) -> None:
        """Registers the table in the view."""
        schema = await self.view.get_schema(event.originator_id)
        if schema is None:
            msg = f"Schema {event.originator_id} is missing from the catalog view"
            raise CatalogProjectionError(msg)
        await self.view.register_table(
            event.table_id,
            schema.schema_id,
            schema.catalog_id,
            event.table_name,
            tracking,
        )

    @dispatch_event.register
    async def _when_table_unregistered(
        self,
        event: Schema.TableUnregistered,
        tracking: Tracking,
    ) -> None:
        """Unregisters the table from the view."""
        await self.view.unregister_table(
            event.originator_id,
            event.table_name,
            tracking,
        )

    @dispatch_event.register
    async def _when_field_added(
        self,
        event: Table.FieldAdded,
        tracking: Tracking,
    ) -> None:
        """Adds the field to the view."""
        await self.view.add_field(
            event.originator_id,
            event.field_name,
            event.data_type,
            event.nullable,
            tracking,
            event.field_id,
        )

    @dispatch_event.register
    async def _when_field_removed(
        self,
        event: Table.FieldRemoved,
        tracking: Tracking,
    ) -> None:
        """Removes the field from the view."""
        await self.view.remove_field(
            event.originator_id,
            event.field_name,
            tracking,
        )

    @dispatch_event.register
    async def _when_field_type_changed(
        self,
        event: Table.FieldTypeChanged,
        tracking: Tracking,
    ) -> None:
        """Changes the data type of the field in the view."""
        await self.view.change_field(
            event.originator_id,
            event.field_name,
            event.data_type,
            None,
            tracking,
        )

    @dispatch_event.register
    async def _when_field_nullability_changed(
        self,
        event: Table.FieldNullabilityChanged,
        tracking: Tracking,
    ) -> None:
        """Changes the nullability of the field in the view."""
        await self.view.change_field(
            event.originator_id,
            event.field_name,
            None,
            event.nullable,
            tracking,
        )

    @dispatch_event.register
    async def _when_field_comment_changed(
        self,
        event: Table.FieldCommentChanged,
        tracking: Tracking,
    ) -> None:
        """Changes the comment of the field in the view."""
        await self.view.change_field(
            event.originator_id,
            event.field_name,
            None,
            None,
            tracking,
            comment=event.comment,
        )

    @dispatch_event.register
    async def _when_catalog_changed(
        self,
        event: Catalog.Changed,
        tracking: Tracking,
    ) -> None:
        """Changes the catalog in the view."""
        await self.view.change_catalog(
            event.originator_id,
            event.name,
            event.description,
            tracking,
        )

    @dispatch_event.register
    async def _when_catalog_discarded(
        self,
        event: Catalog.Discarded,
        tracking: Tracking,
    ) -> None:
        """Discards the catalog and everything it owns in the view."""
        await self.view.discard_catalog(event.originator_id, tracking)

    @dispatch_event.register
    async def _when_schema_name_changed(
        self,
        event: Catalog.SchemaNameChanged,
        tracking: Tracking,
    ) -> None:
        """Renames the schema in the view."""
        await self.view.change_schema(event.schema_id, event.new_name, None, tracking)

    @dispatch_event.register
    async def _when_schema_changed(
        self,
        event: Schema.Changed,
        tracking: Tracking,
    ) -> None:
        """Changes the schema in the view."""
        await self.view.change_schema(
            event.originator_id,
            event.name,
            event.description,
            tracking,
        )

    @dispatch_event.register
    async def _when_schema_discarded(
        self,
        event: Schema.Discarded,
        tracking: Tracking,
    ) -> None:
        """Discards the schema and its tables in the view."""
        await self.view.discard_schema(event.originator_id, tracking)

    @dispatch_event.register
    async def _when_table_name_changed(
        self,
        event: Schema.TableNameChanged,
        tracking: Tracking,
    ) -> None:
        """Renames the table in the view."""
        await self.view.change_table(event.table_id, event.new_name, tracking)

    @dispatch_event.register
    async def _when_table_changed(
        self,
        event: Table.Changed,
        tracking: Tracking,
    ) -> None:
        """Changes the table in the view."""
        await self.view.change_table(
            event.originator_id,
            event.name,
            tracking,
            event.description,
        )

    @dispatch_event.register
    async def _when_table_discarded(
        self,
        event: Table.Discarded,
        tracking: Tracking,
    ) -> None:
        """Discards the table and drops its fields in the view."""
        await self.view.discard_table(event.originator_id, tracking)

    @dispatch_event.register
    async def _when_field_renamed(
        self,
        event: Table.FieldRenamed,
        tracking: Tracking,
    ) -> None:
        """Renames the field in the view."""
        await self.view.rename_field(
            event.originator_id,
            event.old_name,
            event.new_name,
            tracking,
        )


def run_catalog_projection(
    env: EnvType | None = None,
) -> AsyncProjectionRunner[CatalogApplication, CatalogView]:
    """Builds a runner that keeps the catalog view up to date.

    The runner is not started yet: the caller awaits ``start()`` (or uses the
    runner as an async context manager).
    """
    runner = AsyncProjectionRunner[CatalogApplication, CatalogView](
        application_class=CatalogApplication,
        projection_class=CatalogProjection,
        view_class=SQLAlchemyCatalogView,
        env=env,
    )
    get_logger(CatalogProjection.logger_name).info(
        "projection.runner.started",
        application=CatalogApplication.name,
        projection=CatalogProjection.name,
        view=SQLAlchemyCatalogView.__name__,
    )
    return runner
