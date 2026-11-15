"""Projection that materialises the conversation read model."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from eventsourcing.asyncio.application import AsyncApplication
from eventsourcing.asyncio.projection import AsyncProjectionRunner
from eventsourcing.dispatch import singledispatchmethod
from eventsourcing.persistence import JSONTranscoder, Tracking
from eventsourcing.utils import EnvType, get_topic

from etlalchemy.conversation.aggregates.conversation import Conversation
from etlalchemy.conversation.aggregates.transcoding import (
    register_conversation_transcodings,
)
from etlalchemy.conversation.projection.sqlalchemy import SQLAlchemyConversationView
from etlalchemy.conversation.projection.view import (
    ConversationView,
    ResourceAccessRow,
    ToolCallRow,
)
from etlalchemy.shared.logging import get_logger
from etlalchemy.shared.projection import AsyncLoggedProjection


class ConversationEventApplication(AsyncApplication[UUID]):
    """Application used by the projection runner to subscribe to conversation events.

    :class:`~etlalchemy.conversation.application.ConversationApplication` needs
    the read model and the IAM port, so the runner cannot construct it from an
    environment alone. This subclass carries the same application name (and
    therefore the same event store tables) plus the value object transcodings
    the events need to be decoded.
    """

    name = "conversation_application"
    """Application name; must match :class:`ConversationApplication`."""

    def register_transcodings(self, transcoder: JSONTranscoder) -> None:
        """Registers the conversation value object transcodings."""
        super().register_transcodings(transcoder)
        register_conversation_transcodings(transcoder)


class ConversationProjection(AsyncLoggedProjection[ConversationView]):
    """Materialises the conversation read model from the conversation events."""

    name = "conversation_projection"
    """Projection name; used as the environment prefix and tracking table prefix."""

    logger_name = "conversation.projection"
    """Logger used for the per-event trail and for projection failures."""

    topics = (
        get_topic(Conversation.Started),
        get_topic(Conversation.Renamed),
        get_topic(Conversation.ProviderSwitched),
        get_topic(Conversation.UserMessageAppended),
        get_topic(Conversation.UserMessageEdited),
        get_topic(Conversation.AssistantMessageCompleted),
        get_topic(Conversation.AssistantMessageReasoned),
        get_topic(Conversation.RunStarted),
        get_topic(Conversation.ApprovalRequested),
        get_topic(Conversation.ApprovalDecided),
        get_topic(Conversation.RunFinished),
        get_topic(Conversation.Discarded),
    )

    @singledispatchmethod
    async def dispatch_event(self, domain_event: Any, tracking: Tracking) -> None:
        """Ignores events that are not handled by this projection."""

    @dispatch_event.register
    async def _when_started(self, event: Conversation.Started, tracking: Tracking) -> None:
        """Registers the conversation in the view."""
        await self.view.register_conversation(
            event.originator_id,
            event.user_id,
            event.tenant_id,
            event.title,
            event.active_llm_provider_id,
            event.created_at,
            tracking,
        )

    @dispatch_event.register
    async def _when_renamed(self, event: Conversation.Renamed, tracking: Tracking) -> None:
        """Changes the conversation title in the view."""
        await self.view.rename_conversation(event.originator_id, event.title, tracking)

    @dispatch_event.register
    async def _when_provider_switched(
        self,
        event: Conversation.ProviderSwitched,
        tracking: Tracking,
    ) -> None:
        """Changes the selected provider in the view."""
        await self.view.switch_provider(event.originator_id, event.provider_id, tracking)

    @dispatch_event.register
    async def _when_user_message_appended(
        self,
        event: Conversation.UserMessageAppended,
        tracking: Tracking,
    ) -> None:
        """Registers a user message in the view."""
        await self.view.append_message(
            event.message_id,
            event.originator_id,
            "user",
            event.content,
            event.created_at,
            tracking,
        )

    @dispatch_event.register
    async def _when_user_message_edited(
        self,
        event: Conversation.UserMessageEdited,
        tracking: Tracking,
    ) -> None:
        """Rewrites a user message and drops its successors in the view."""
        await self.view.edit_message(
            event.originator_id,
            event.message_id,
            event.content,
            event.removed_message_ids,
            event.removed_run_ids,
            event.edited_at,
            tracking,
        )

    @dispatch_event.register
    async def _when_assistant_message_completed(
        self,
        event: Conversation.AssistantMessageCompleted,
        tracking: Tracking,
    ) -> None:
        """Registers an assistant message with its trace in the view."""
        await self.view.complete_message(
            event.message_id,
            event.originator_id,
            "assistant",
            event.content,
            event.interrupted,
            event.token_usage.input_tokens,
            event.token_usage.output_tokens,
            [
                ResourceAccessRow(
                    uri=item.uri,
                    size_bytes=item.size_bytes,
                    mime_type=item.mime_type,
                    read_at=item.at,
                )
                for item in event.resources
            ],
            [
                ToolCallRow(
                    tool=item.tool,
                    args_hash=item.args_hash,
                    status=item.status,
                    duration_ms=item.duration_ms,
                    error_code=item.error_code,
                    args_json=item.args_json,
                    result_preview=item.result_preview,
                )
                for item in event.tools
            ],
            event.created_at,
            tracking,
        )

    @dispatch_event.register
    async def _when_assistant_message_reasoned(
        self,
        event: Conversation.AssistantMessageReasoned,
        tracking: Tracking,
    ) -> None:
        """Stores the thinking of an assistant message in the view."""
        await self.view.record_reasoning(event.message_id, event.reasoning, tracking)

    @dispatch_event.register
    async def _when_run_started(self, event: Conversation.RunStarted, tracking: Tracking) -> None:
        """Registers a run in the view."""
        await self.view.start_run(
            event.run_id,
            event.originator_id,
            event.message_id,
            event.started_at,
            tracking,
        )

    @dispatch_event.register
    async def _when_approval_requested(
        self,
        event: Conversation.ApprovalRequested,
        tracking: Tracking,
    ) -> None:
        """Registers a pending approval in the view."""
        await self.view.request_approval(
            event.approval_id,
            event.run_id,
            event.originator_id,
            event.tool,
            event.args_hash,
            event.reason,
            event.requested_at,
            tracking,
        )

    @dispatch_event.register
    async def _when_approval_decided(
        self,
        event: Conversation.ApprovalDecided,
        tracking: Tracking,
    ) -> None:
        """Finalises an approval in the view."""
        await self.view.decide_approval(
            event.approval_id,
            event.approved,
            event.decided_by,
            event.decided_at,
            tracking,
        )

    @dispatch_event.register
    async def _when_run_finished(
        self,
        event: Conversation.RunFinished,
        tracking: Tracking,
    ) -> None:
        """Finalises a run in the view."""
        await self.view.finish_run(
            event.run_id,
            event.status,
            event.finished_at,
            event.error,
            tracking,
        )

    @dispatch_event.register
    async def _when_discarded(self, event: Conversation.Discarded, tracking: Tracking) -> None:
        """Soft-deletes the conversation and its messages in the view."""
        await self.view.discard_conversation(event.originator_id, event.at, tracking)


def run_conversation_projection(
    env: EnvType | None = None,
) -> AsyncProjectionRunner[ConversationEventApplication, ConversationView]:
    """Builds a runner that keeps the conversation view up to date.

    The runner is not started yet: the caller awaits ``start()`` (or uses the
    runner as an async context manager).
    """
    runner = AsyncProjectionRunner[ConversationEventApplication, ConversationView](
        application_class=ConversationEventApplication,
        projection_class=ConversationProjection,
        view_class=SQLAlchemyConversationView,
        env=env,
    )
    get_logger(ConversationProjection.logger_name).info(
        "projection.runner.started",
        application=ConversationEventApplication.name,
        projection=ConversationProjection.name,
        view=SQLAlchemyConversationView.__name__,
    )
    return runner
