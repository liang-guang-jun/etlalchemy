"""Projection that materialises the comment read model."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from eventsourcing.asyncio.application import AsyncApplication
from eventsourcing.asyncio.projection import AsyncProjectionRunner
from eventsourcing.dispatch import singledispatchmethod
from eventsourcing.persistence import Tracking
from eventsourcing.utils import EnvType, get_topic

from etlalchemy.comment.aggregates.thread import Thread
from etlalchemy.comment.projection.sqlalchemy import SQLAlchemyCommentView
from etlalchemy.comment.projection.view import CommentView
from etlalchemy.shared.logging import get_logger
from etlalchemy.shared.projection import AsyncLoggedProjection


class CommentEventApplication(AsyncApplication[UUID]):
    """Application used by the projection runner to subscribe to comment events.

    :class:`~etlalchemy.comment.application.CommentApplication` needs the IAM
    context and the target lookups, so the projection runner cannot construct it
    from an environment alone. This subclass carries the same application name
    (and therefore the same event store tables) without the use-case
    dependencies.
    """

    name = "comment_application"
    """Application name; must match :class:`CommentApplication`."""


class CommentProjection(AsyncLoggedProjection[CommentView]):
    """Materialises the comment read model from the comment events.

    Every event carries the state the view needs, so no handler has to read the
    aggregate back.
    """

    name = "comment_projection"
    """Projection name; used as the environment prefix and tracking table prefix."""

    logger_name = "comment.projection"
    """Logger used for the per-event trail and for projection failures."""

    topics = (
        get_topic(Thread.Started),
        get_topic(Thread.CommentAdded),
        get_topic(Thread.CommentEdited),
        get_topic(Thread.CommentDiscarded),
        get_topic(Thread.Resolved),
        get_topic(Thread.Reopened),
        get_topic(Thread.Discarded),
    )

    @singledispatchmethod
    async def dispatch_event(self, domain_event: Any, tracking: Tracking) -> None:
        """Ignores events that are not handled by this projection."""

    @dispatch_event.register
    async def _when_started(self, event: Thread.Started, tracking: Tracking) -> None:
        """Registers the thread and its root comment in the view."""
        await self.view.register_thread(
            event.originator_id,
            event.target_type,
            event.target_id,
            event.title,
            event.author_user_id,
            event.author_tenant_id,
            event.root_comment_id,
            event.body,
            list(event.mentions),
            event.created_at,
            tracking,
        )

    @dispatch_event.register
    async def _when_comment_added(self, event: Thread.CommentAdded, tracking: Tracking) -> None:
        """Registers the comment and refreshes the thread activity."""
        await self.view.add_comment(
            event.comment_id,
            event.originator_id,
            event.parent_comment_id,
            event.author_user_id,
            event.author_tenant_id,
            event.body,
            list(event.mentions),
            event.created_at,
            tracking,
        )

    @dispatch_event.register
    async def _when_comment_edited(self, event: Thread.CommentEdited, tracking: Tracking) -> None:
        """Replaces the body and mentions of the comment."""
        await self.view.edit_comment(
            event.comment_id,
            event.originator_id,
            event.author_user_id,
            event.body,
            list(event.mentions),
            event.edited_at,
            tracking,
        )

    @dispatch_event.register
    async def _when_comment_discarded(
        self,
        event: Thread.CommentDiscarded,
        tracking: Tracking,
    ) -> None:
        """Soft-deletes the comment and refreshes the live count."""
        await self.view.discard_comment(
            event.comment_id,
            event.originator_id,
            event.discarded_at,
            tracking,
        )

    @dispatch_event.register
    async def _when_resolved(self, event: Thread.Resolved, tracking: Tracking) -> None:
        """Marks the thread as resolved."""
        await self.view.resolve_thread(
            event.originator_id,
            event.by_user_id,
            event.at,
            tracking,
        )

    @dispatch_event.register
    async def _when_reopened(self, event: Thread.Reopened, tracking: Tracking) -> None:
        """Reopens the thread."""
        await self.view.reopen_thread(event.originator_id, event.at, tracking)

    @dispatch_event.register
    async def _when_discarded(self, event: Thread.Discarded, tracking: Tracking) -> None:
        """Soft-deletes the thread."""
        await self.view.discard_thread(event.originator_id, event.at, tracking)


def run_comment_projection(
    env: EnvType,
) -> AsyncProjectionRunner[CommentEventApplication, CommentView]:
    """Builds a runner that keeps the comment view up to date.

    The runner is not started yet: the caller awaits ``start()`` (or uses the
    runner as an async context manager).
    """
    runner = AsyncProjectionRunner[CommentEventApplication, CommentView](
        application_class=CommentEventApplication,
        projection_class=CommentProjection,
        view_class=SQLAlchemyCommentView,
        env=env,
    )
    get_logger(CommentProjection.logger_name).info(
        "projection.runner.started",
        application=CommentEventApplication.name,
        projection=CommentProjection.name,
        view=SQLAlchemyCommentView.__name__,
    )
    return runner
