"""Projection that materialises the LLM provider read model."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from eventsourcing.dispatch import singledispatchmethod
from eventsourcing.persistence import Tracking
from eventsourcing.utils import EnvType, get_topic

from etlalchemy._vendor.eventsourcing.asyncio.application import AsyncApplication
from etlalchemy._vendor.eventsourcing.asyncio.projection import AsyncProjectionRunner
from etlalchemy.llm_config.aggregates.provider import LlmProvider
from etlalchemy.llm_config.projection.sqlalchemy import SQLAlchemyLlmProviderView
from etlalchemy.llm_config.projection.view import LlmProviderView
from etlalchemy.shared.logging import get_logger
from etlalchemy.shared.projection import AsyncLoggedProjection


class LlmConfigEventApplication(AsyncApplication[UUID]):
    """Application used by the projection runner to subscribe to provider events.

    :class:`~etlalchemy.llm_config.application.LlmConfigApplication` needs the
    read model and the IAM port, so the projection runner cannot construct it
    from an environment alone. This subclass carries the same application name
    (and therefore the same event store tables) without those dependencies.
    """

    name = "llm_config_application"
    """Application name; must match :class:`LlmConfigApplication`."""


class LlmConfigProjection(AsyncLoggedProjection[LlmProviderView]):
    """Materialises the LLM provider read model from the provider events."""

    name = "llm_config_projection"
    """Projection name; used as the environment prefix and tracking table prefix."""

    logger_name = "llm_config.projection"
    """Logger used for the per-event trail and for projection failures."""

    topics = (
        get_topic(LlmProvider.Started),
        get_topic(LlmProvider.Renamed),
        get_topic(LlmProvider.EndpointChanged),
        get_topic(LlmProvider.DefaultModelChanged),
        get_topic(LlmProvider.OptionsChanged),
        get_topic(LlmProvider.CredentialRotated),
        get_topic(LlmProvider.SharingChanged),
        get_topic(LlmProvider.SystemDefaultChanged),
        get_topic(LlmProvider.TenantDefaultChanged),
        get_topic(LlmProvider.UserDefaultChanged),
        get_topic(LlmProvider.Discarded),
    )

    @singledispatchmethod
    async def dispatch_event(self, domain_event: Any, tracking: Tracking) -> None:
        """Ignores events that are not handled by this projection."""

    @dispatch_event.register
    async def _when_started(self, event: LlmProvider.Started, tracking: Tracking) -> None:
        """Registers the provider in the view."""
        await self.view.register_provider(
            event.originator_id,
            event.name,
            event.kind,
            event.endpoint,
            event.credential_ref,
            event.token is not None,
            event.default_model,
            event.options,
            event.owner_user_id,
            event.tenant_id,
            event.is_public,
            event.timestamp,
            tracking,
        )

    @dispatch_event.register
    async def _when_renamed(self, event: LlmProvider.Renamed, tracking: Tracking) -> None:
        """Changes the provider name in the view."""
        await self.view.rename_provider(event.originator_id, event.name, tracking)

    @dispatch_event.register
    async def _when_endpoint_changed(
        self,
        event: LlmProvider.EndpointChanged,
        tracking: Tracking,
    ) -> None:
        """Changes the provider endpoint in the view."""
        await self.view.change_endpoint(event.originator_id, event.endpoint, tracking)

    @dispatch_event.register
    async def _when_default_model_changed(
        self,
        event: LlmProvider.DefaultModelChanged,
        tracking: Tracking,
    ) -> None:
        """Changes the default model in the view."""
        await self.view.change_default_model(
            event.originator_id,
            event.default_model,
            tracking,
        )

    @dispatch_event.register
    async def _when_options_changed(
        self,
        event: LlmProvider.OptionsChanged,
        tracking: Tracking,
    ) -> None:
        """Replaces the model options in the view."""
        await self.view.change_options(event.originator_id, event.options, tracking)

    @dispatch_event.register
    async def _when_credential_rotated(
        self,
        event: LlmProvider.CredentialRotated,
        tracking: Tracking,
    ) -> None:
        """Updates the credential pointer in the view."""
        await self.view.rotate_credential(
            event.originator_id,
            event.credential_ref,
            event.token is not None,
            tracking,
        )

    @dispatch_event.register
    async def _when_sharing_changed(
        self,
        event: LlmProvider.SharingChanged,
        tracking: Tracking,
    ) -> None:
        """Replaces the shares of the provider in the view."""
        await self.view.set_sharing(
            event.originator_id,
            list(event.shared_with_user_ids),
            list(event.shared_with_group_ids),
            tracking,
        )

    @dispatch_event.register
    async def _when_system_default_changed(
        self,
        event: LlmProvider.SystemDefaultChanged,
        tracking: Tracking,
    ) -> None:
        """Updates the system default pointer in the view."""
        await self.view.set_default(
            event.originator_id,
            "system",
            None,
            event.enabled,
            tracking,
        )

    @dispatch_event.register
    async def _when_tenant_default_changed(
        self,
        event: LlmProvider.TenantDefaultChanged,
        tracking: Tracking,
    ) -> None:
        """Updates a tenant default pointer in the view."""
        await self.view.set_default(
            event.originator_id,
            "tenant",
            event.tenant_id,
            event.enabled,
            tracking,
        )

    @dispatch_event.register
    async def _when_user_default_changed(
        self,
        event: LlmProvider.UserDefaultChanged,
        tracking: Tracking,
    ) -> None:
        """Updates a user default pointer in the view."""
        await self.view.set_default(
            event.originator_id,
            "user",
            event.user_id,
            event.enabled,
            tracking,
        )

    @dispatch_event.register
    async def _when_discarded(self, event: LlmProvider.Discarded, tracking: Tracking) -> None:
        """Soft-deletes the provider and drops its pointers."""
        await self.view.discard_provider(event.originator_id, tracking)


def run_llm_config_projection(
    env: EnvType | None = None,
) -> AsyncProjectionRunner[LlmConfigEventApplication, LlmProviderView]:
    """Builds a runner that keeps the LLM provider view up to date.

    The runner is not started yet: the caller awaits ``start()`` (or uses the
    runner as an async context manager).
    """
    runner = AsyncProjectionRunner[LlmConfigEventApplication, LlmProviderView](
        application_class=LlmConfigEventApplication,
        projection_class=LlmConfigProjection,
        view_class=SQLAlchemyLlmProviderView,
        env=env,
    )
    get_logger(LlmConfigProjection.logger_name).info(
        "projection.runner.started",
        application=LlmConfigEventApplication.name,
        projection=LlmConfigProjection.name,
        view=SQLAlchemyLlmProviderView.__name__,
    )
    return runner
