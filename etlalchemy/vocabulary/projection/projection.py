"""Projection that materialises the vocabulary read model."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from eventsourcing.dispatch import singledispatchmethod
from eventsourcing.persistence import Tracking
from eventsourcing.utils import EnvType, get_topic

from etlalchemy._vendor.eventsourcing.asyncio.application import AsyncApplication
from etlalchemy._vendor.eventsourcing.asyncio.projection import AsyncProjectionRunner
from etlalchemy.shared.logging import get_logger
from etlalchemy.shared.projection import AsyncLoggedProjection
from etlalchemy.vocabulary.aggregates.domain import Domain
from etlalchemy.vocabulary.aggregates.term import Term
from etlalchemy.vocabulary.aggregates.types import TermStatus
from etlalchemy.vocabulary.projection.sqlalchemy import SQLAlchemyVocabularyView
from etlalchemy.vocabulary.projection.view import VocabularyView


class VocabularyEventApplication(AsyncApplication[UUID]):
    """Application used by the projection runner to subscribe to vocabulary events.

    :class:`~etlalchemy.vocabulary.application.VocabularyApplication` needs the
    catalog read model, so the projection runner cannot construct it from an
    environment alone. This subclass carries the same application name (and
    therefore the same event store tables) without the use-case dependencies.
    """

    name = "vocabulary_application"
    """Application name; must match :class:`VocabularyApplication`."""


class VocabularyProjection(AsyncLoggedProjection[VocabularyView]):
    """Materialises the vocabulary read model from the vocabulary events.

    Only events that change the view are topics. The registry events
    (``Domain.TermRegistered``, ``Domain.TermUnregistered`` and
    ``Domain.TermRepathed``) are consumed by the application's addressing logic,
    not by the read model: every row is maintained by the term's own events, and
    each event already carries the resulting path.
    """

    name = "vocabulary_projection"
    """Projection name; used as the environment prefix and tracking table prefix."""

    logger_name = "vocabulary.projection"
    """Logger used for the per-event trail and for projection failures."""

    topics = (
        get_topic(Domain.Started),
        get_topic(Domain.Changed),
        get_topic(Domain.Discarded),
        get_topic(Term.Started),
        get_topic(Term.ColorChanged),
        get_topic(Term.DefinitionChanged),
        get_topic(Term.AliasAdded),
        get_topic(Term.AliasRemoved),
        get_topic(Term.Approved),
        get_topic(Term.Reopened),
        get_topic(Term.Deprecated),
        get_topic(Term.Reactivated),
        get_topic(Term.Linked),
        get_topic(Term.Unlinked),
        get_topic(Term.Renamed),
        get_topic(Term.Moved),
        get_topic(Term.Repathed),
        get_topic(Term.Discarded),
    )

    @singledispatchmethod
    async def dispatch_event(self, domain_event: Any, tracking: Tracking) -> None:
        """Ignores events that are not handled by this projection."""

    @dispatch_event.register
    async def _when_domain_started(self, event: Domain.Started, tracking: Tracking) -> None:
        """Registers the domain in the view."""
        await self.view.register_domain(
            event.originator_id,
            event.name,
            event.description,
            tracking,
        )

    @dispatch_event.register
    async def _when_domain_changed(self, event: Domain.Changed, tracking: Tracking) -> None:
        """Changes the domain in the view."""
        await self.view.change_domain(
            event.originator_id,
            event.name,
            event.description,
            tracking,
        )

    @dispatch_event.register
    async def _when_domain_discarded(self, event: Domain.Discarded, tracking: Tracking) -> None:
        """Discards the domain and every term it owns in the view."""
        await self.view.discard_domain(event.originator_id, tracking)

    @dispatch_event.register
    async def _when_term_started(self, event: Term.Started, tracking: Tracking) -> None:
        """Registers the term and its aliases in the view."""
        await self.view.register_term(
            event.originator_id,
            event.domain_id,
            event.parent_id,
            event.path,
            event.name,
            event.definition,
            list(event.aliases),
            tracking,
            event.color,
        )

    @dispatch_event.register
    async def _when_color_changed(self, event: Term.ColorChanged, tracking: Tracking) -> None:
        """Sets the colour of the term in the view."""
        await self.view.set_term_color(event.originator_id, event.color, tracking)

    @dispatch_event.register
    async def _when_definition_changed(
        self,
        event: Term.DefinitionChanged,
        tracking: Tracking,
    ) -> None:
        """Replaces the definition of the term in the view."""
        await self.view.change_term_definition(event.originator_id, event.definition, tracking)

    @dispatch_event.register
    async def _when_alias_added(self, event: Term.AliasAdded, tracking: Tracking) -> None:
        """Adds the alias to the term in the view."""
        await self.view.add_term_alias(event.originator_id, event.alias, tracking)

    @dispatch_event.register
    async def _when_alias_removed(self, event: Term.AliasRemoved, tracking: Tracking) -> None:
        """Removes the alias from the term in the view."""
        await self.view.remove_term_alias(event.originator_id, event.alias, tracking)

    @dispatch_event.register
    async def _when_approved(self, event: Term.Approved, tracking: Tracking) -> None:
        """Marks the term as approved in the view."""
        await self.view.set_term_status(
            event.originator_id,
            TermStatus.APPROVED.value,
            tracking,
        )

    @dispatch_event.register
    async def _when_reopened(self, event: Term.Reopened, tracking: Tracking) -> None:
        """Marks the term as a draft in the view."""
        await self.view.set_term_status(
            event.originator_id,
            TermStatus.DRAFT.value,
            tracking,
        )

    @dispatch_event.register
    async def _when_deprecated(self, event: Term.Deprecated, tracking: Tracking) -> None:
        """Marks the term as deprecated in the view."""
        await self.view.set_term_status(
            event.originator_id,
            TermStatus.DEPRECATED.value,
            tracking,
        )

    @dispatch_event.register
    async def _when_reactivated(self, event: Term.Reactivated, tracking: Tracking) -> None:
        """Marks the term as a draft in the view."""
        await self.view.set_term_status(
            event.originator_id,
            TermStatus.DRAFT.value,
            tracking,
        )

    @dispatch_event.register
    async def _when_linked(self, event: Term.Linked, tracking: Tracking) -> None:
        """Records the link in the view."""
        await self.view.link_term(
            event.originator_id,
            event.target_id,
            event.target_kind,
            event.field_name,
            tracking,
        )

    @dispatch_event.register
    async def _when_unlinked(self, event: Term.Unlinked, tracking: Tracking) -> None:
        """Removes the link from the view."""
        await self.view.unlink_term(
            event.originator_id,
            event.target_id,
            event.target_kind,
            event.field_name,
            tracking,
        )

    @dispatch_event.register
    async def _when_renamed(self, event: Term.Renamed, tracking: Tracking) -> None:
        """Renames the term in the view."""
        await self.view.rename_term(
            event.originator_id,
            event.new_name,
            event.new_path,
            tracking,
        )

    @dispatch_event.register
    async def _when_moved(self, event: Term.Moved, tracking: Tracking) -> None:
        """Moves the term in the view."""
        await self.view.move_term(
            event.originator_id,
            event.parent_id,
            event.new_path,
            tracking,
        )

    @dispatch_event.register
    async def _when_repathed(self, event: Term.Repathed, tracking: Tracking) -> None:
        """Changes the path of the term in the view."""
        await self.view.repath_term(event.originator_id, event.new_path, tracking)

    @dispatch_event.register
    async def _when_term_discarded(self, event: Term.Discarded, tracking: Tracking) -> None:
        """Discards the term and drops its aliases and links in the view."""
        await self.view.discard_term(event.originator_id, tracking)


def run_vocabulary_projection(
    env: EnvType | None = None,
) -> AsyncProjectionRunner[VocabularyEventApplication, VocabularyView]:
    """Builds a runner that keeps the vocabulary view up to date.

    The runner is not started yet: the caller awaits ``start()`` (or uses the
    runner as an async context manager).
    """
    runner = AsyncProjectionRunner[VocabularyEventApplication, VocabularyView](
        application_class=VocabularyEventApplication,
        projection_class=VocabularyProjection,
        view_class=SQLAlchemyVocabularyView,
        env=env,
    )
    get_logger(VocabularyProjection.logger_name).info(
        "projection.runner.started",
        application=VocabularyEventApplication.name,
        projection=VocabularyProjection.name,
        view=SQLAlchemyVocabularyView.__name__,
    )
    return runner
