"""Projection that materialises the ingestion read model."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from eventsourcing.dispatch import singledispatchmethod
from eventsourcing.persistence import Tracking
from eventsourcing.utils import EnvType, get_topic

from etlalchemy._vendor.eventsourcing.asyncio.application import AsyncApplication
from etlalchemy._vendor.eventsourcing.asyncio.projection import AsyncProjectionRunner
from etlalchemy.ingestion.aggregates.connection import SourceConnection
from etlalchemy.ingestion.aggregates.import_run import ImportRun
from etlalchemy.ingestion.projection.sqlalchemy import SQLAlchemyIngestionView
from etlalchemy.ingestion.projection.view import IngestionView
from etlalchemy.shared.logging import get_logger
from etlalchemy.shared.projection import AsyncLoggedProjection


class IngestionEventApplication(AsyncApplication[UUID]):
    """Application used by the projection runner to subscribe to ingestion events.

    :class:`~etlalchemy.ingestion.application.IngestionApplication` needs the
    catalog application, the read models and the secret resolver, so the
    projection runner cannot construct it from an environment alone. This
    subclass carries the same application name (and therefore the same event
    store tables) without the use-case dependencies.
    """

    name = "ingestion_application"
    """Application name; must match :class:`IngestionApplication`."""


class IngestionProjection(AsyncLoggedProjection[IngestionView]):
    """Materialises the ingestion read model from the ingestion events."""

    name = "ingestion_projection"
    """Projection name; used as the environment prefix and tracking table prefix."""

    logger_name = "ingestion.projection"
    """Logger used for the per-event trail and for projection failures."""

    topics = (
        get_topic(SourceConnection.Started),
        get_topic(SourceConnection.Changed),
        get_topic(SourceConnection.CredentialRotated),
        get_topic(SourceConnection.Discarded),
        get_topic(ImportRun.Started),
        get_topic(ImportRun.Succeeded),
        get_topic(ImportRun.Failed),
        get_topic(ImportRun.Abandoned),
    )

    @singledispatchmethod
    async def dispatch_event(self, domain_event: Any, tracking: Tracking) -> None:
        """Ignores events that are not handled by this projection."""

    @dispatch_event.register
    async def _when_connection_started(
        self,
        event: SourceConnection.Started,
        tracking: Tracking,
    ) -> None:
        """Registers the connection in the view."""
        await self.view.register_connection(
            event.originator_id,
            event.name,
            event.kind,
            event.endpoint,
            event.credential_ref,
            event.token is not None,
            event.default_catalog,
            event.options,
            tracking,
        )

    @dispatch_event.register
    async def _when_connection_changed(
        self,
        event: SourceConnection.Changed,
        tracking: Tracking,
    ) -> None:
        """Changes the connection in the view."""
        await self.view.change_connection(
            event.originator_id,
            event.name,
            event.endpoint,
            event.default_catalog,
            event.options,
            tracking,
        )

    @dispatch_event.register
    async def _when_credential_rotated(
        self,
        event: SourceConnection.CredentialRotated,
        tracking: Tracking,
    ) -> None:
        """Updates the credential pointer of the connection in the view."""
        await self.view.rotate_credential(
            event.originator_id,
            event.credential_ref,
            event.token is not None,
            tracking,
        )

    @dispatch_event.register
    async def _when_connection_discarded(
        self,
        event: SourceConnection.Discarded,
        tracking: Tracking,
    ) -> None:
        """Discards the connection in the view."""
        await self.view.discard_connection(event.originator_id, tracking)

    @dispatch_event.register
    async def _when_run_started(
        self,
        event: ImportRun.Started,
        tracking: Tracking,
    ) -> None:
        """Registers the run in the view."""
        await self.view.register_import_run(
            event.originator_id,
            event.connection_id,
            event.target_catalog_id,
            event.source_catalog,
            event.include_schemas or [],
            event.include_tables or {},
            event.schema_mapping or {},
            tracking,
        )

    @dispatch_event.register
    async def _when_run_succeeded(
        self,
        event: ImportRun.Succeeded,
        tracking: Tracking,
    ) -> None:
        """Finalises the run as succeeded."""
        await self.view.finish_import_run(
            event.originator_id,
            "succeeded",
            event.schema_count,
            event.table_count,
            event.field_count,
            None,
            tracking,
        )

    @dispatch_event.register
    async def _when_run_failed(
        self,
        event: ImportRun.Failed,
        tracking: Tracking,
    ) -> None:
        """Finalises the run as failed."""
        await self.view.finish_import_run(
            event.originator_id,
            "failed",
            event.schema_count,
            event.table_count,
            event.field_count,
            event.error,
            tracking,
        )

    @dispatch_event.register
    async def _when_run_abandoned(
        self,
        event: ImportRun.Abandoned,
        tracking: Tracking,
    ) -> None:
        """Finalises a stale pending run as abandoned."""
        await self.view.finish_import_run(
            event.originator_id,
            "abandoned",
            0,
            0,
            0,
            event.reason,
            tracking,
        )


def run_ingestion_projection(
    env: EnvType | None = None,
) -> AsyncProjectionRunner[IngestionEventApplication, IngestionView]:
    """Builds a runner that keeps the ingestion view up to date.

    The runner is not started yet: the caller awaits ``start()`` (or uses the
    runner as an async context manager).
    """
    runner = AsyncProjectionRunner[IngestionEventApplication, IngestionView](
        application_class=IngestionEventApplication,
        projection_class=IngestionProjection,
        view_class=SQLAlchemyIngestionView,
        env=env,
    )
    get_logger(IngestionProjection.logger_name).info(
        "projection.runner.started",
        application=IngestionEventApplication.name,
        projection=IngestionProjection.name,
        view=SQLAlchemyIngestionView.__name__,
    )
    return runner
