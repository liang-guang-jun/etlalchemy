"""Application service exposing the conversation use cases."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

import structlog
from eventsourcing.application import AggregateNotFoundError
from eventsourcing.persistence import JSONTranscoder, RecordConflictError
from eventsourcing.utils import EnvType

from etlalchemy._vendor.eventsourcing.asyncio.application import AsyncApplication
from etlalchemy.conversation.aggregates.conversation import Conversation
from etlalchemy.conversation.aggregates.errors import (
    InvalidRunTransitionError,
    RunInProgressError,
    UnknownConversationError,
    UnknownRunError,
)
from etlalchemy.conversation.aggregates.transcoding import (
    register_conversation_transcodings,
)
from etlalchemy.conversation.aggregates.types import (
    ResourceAccess,
    RunStatus,
    TokenUsage,
    ToolCallRecord,
    clamp_content,
)
from etlalchemy.conversation.projection.view import (
    ApprovalRow,
    ConversationRow,
    ConversationView,
    MessageRow,
    RunRow,
)
from etlalchemy.iam.aggregates.errors import PermissionDeniedError
from etlalchemy.shared.logging import get_logger

if TYPE_CHECKING:
    from etlalchemy.conversation.ports.authorization import (
        ConversationAuthorizationPort,
        SessionUser,
    )


@dataclass(frozen=True)
class ConversationOptions:
    """Policy and pagination settings of the conversation context."""

    max_messages_per_conversation: int = 10_000
    """Hard cap on the messages of one conversation."""
    max_message_chars: int = 262_144
    """Maximum length of a user message body."""
    max_assistant_chars: int = 262_144
    """Maximum length of an assistant message body before it is truncated."""
    default_page_size: int = 50
    """Page size used when a read does not specify one."""
    max_page_size: int = 200
    """Upper bound of every page size."""
    run_stale_after_seconds: int = 180
    """Age after which a running run stops blocking new messages; 0 disables."""


@dataclass(frozen=True)
class MessageRef:
    """Result of ``append_user_message``."""

    message_id: UUID
    """ID of the stored message."""
    conversation_id: UUID
    """ID of the conversation that owns the message."""


@dataclass(frozen=True)
class RunRef:
    """Result of ``start_run``."""

    run_id: UUID
    """ID of the run."""
    conversation_id: UUID
    """ID of the conversation that owns the run."""


class ConversationApplication(AsyncApplication[UUID]):
    """Application service for the conversation context.

    A conversation belongs to one user; only that user (or a system
    administrator) may read or change it.
    """

    name = "conversation_application"
    """Application name; the eventsourcing factories derive table names from it."""

    def __init__(
        self,
        view: ConversationView,
        iam: ConversationAuthorizationPort,
        options: ConversationOptions | None = None,
        env: EnvType | None = None,
    ) -> None:
        """Wires the read model and the IAM port."""
        super().__init__(env=env)
        self._view = view
        self._iam = iam
        self._options = options or ConversationOptions()
        self._log: structlog.stdlib.BoundLogger = get_logger("conversation.application")

    def register_transcodings(self, transcoder: JSONTranscoder) -> None:
        """Registers the conversation value object transcodings."""
        super().register_transcodings(transcoder)
        register_conversation_transcodings(transcoder)

    # -- writes -------------------------------------------------------------

    async def start_conversation(
        self,
        session_id: UUID,
        title: str = "",
        active_llm_provider_id: UUID | None = None,
        tenant_id: UUID | None = None,
    ) -> UUID:
        """Starts an empty conversation and returns its id."""
        self._log.info("conversation.start")
        session = await self._iam.session_user(session_id)
        conversation = Conversation(
            user_id=session.user_id,
            tenant_id=tenant_id if tenant_id is not None else session.tenant_id,
            created_at=datetime.now(UTC),
            title=title,
            active_llm_provider_id=active_llm_provider_id,
        )
        await self.save(conversation)
        self._log.info("conversation.start done", conversation_id=str(conversation.id))
        return conversation.id

    async def rename_conversation(
        self,
        session_id: UUID,
        conversation_id: UUID,
        title: str,
    ) -> None:
        """Changes the title of a conversation."""
        session = await self._iam.session_user(session_id)
        conversation = await self._owned(session, conversation_id)
        conversation.rename(title)
        await self.save(conversation)

    async def switch_llm_provider(
        self,
        session_id: UUID,
        conversation_id: UUID,
        provider_id: UUID | None,
    ) -> None:
        """Selects the LLM provider the next message of a conversation uses."""
        session = await self._iam.session_user(session_id)
        conversation = await self._owned(session, conversation_id)
        conversation.switch_provider(provider_id)
        await self.save(conversation)

    async def append_user_message(
        self,
        session_id: UUID,
        conversation_id: UUID,
        content: str,
        message_id: UUID | None = None,
    ) -> MessageRef:
        """Records a user message before the run that answers it starts."""
        self._log.info("conversation.message.user start", conversation_id=str(conversation_id))
        session = await self._iam.session_user(session_id)
        # The stale check may close an abandoned run, which writes the aggregate:
        # load it afterwards, or this save would lose the version race with itself.
        await self._ensure_no_running_run(conversation_id)
        conversation = await self._owned(session, conversation_id)
        resolved = message_id or uuid4()
        conversation.append_user_message(
            resolved,
            content,
            datetime.now(UTC),
            self._options.max_messages_per_conversation,
            self._options.max_message_chars,
        )
        await self.save(conversation)
        self._log.info("conversation.message.user done", message_id=str(resolved))
        return MessageRef(message_id=resolved, conversation_id=conversation_id)

    async def edit_user_message(
        self,
        session_id: UUID,
        conversation_id: UUID,
        message_id: UUID,
        content: str,
    ) -> tuple[tuple[str, str], ...]:
        """Rewrites a user message, drops its successors and returns the history.

        The returned history holds the messages before the edited one, oldest
        first, so a regenerated run replays that context directly instead of
        waiting for the projection to apply the truncation.

        Args:
            session_id: Session that edits the message.
            conversation_id: Conversation the message belongs to.
            message_id: User message to rewrite.
            content: New body.

        Returns:
            ``(role, content)`` pairs of the messages before the edited one.

        Raises:
            UnknownConversationError: If the conversation does not exist.
            UnknownMessageError: If the id is not a user message.
            RunInProgressError: If a run of the conversation is still running.
        """
        self._log.info(
            "conversation.message.edit start",
            conversation_id=str(conversation_id),
            message_id=str(message_id),
        )
        session = await self._iam.session_user(session_id)
        # The stale check may close an abandoned run, which writes the aggregate:
        # load it afterwards, or this save would lose the version race with itself.
        await self._ensure_no_running_run(conversation_id)
        conversation = await self._owned(session, conversation_id)
        conversation.edit_user_message(
            message_id,
            content,
            datetime.now(UTC),
            self._options.max_message_chars,
        )
        await self.save(conversation)
        history = tuple(
            (message.role, message.content)
            for message in conversation.messages.values()
            if message.message_id != message_id and message.content.strip()
        )
        self._log.info(
            "conversation.message.edit done",
            conversation_id=str(conversation_id),
            message_id=str(message_id),
            kept=len(history),
        )
        return history

    async def complete_assistant_message(
        self,
        session_id: UUID,
        conversation_id: UUID,
        content: str,
        message_id: UUID | None = None,
        resources: tuple[ResourceAccess, ...] = (),
        tools: tuple[ToolCallRecord, ...] = (),
        token_usage: TokenUsage | None = None,
        interrupted: bool = False,
        reasoning: str = "",
    ) -> MessageRef:
        """Records the assistant answer with its trace, truncating a long body."""
        self._log.info(
            "conversation.message.assistant start",
            conversation_id=str(conversation_id),
            interrupted=interrupted,
        )
        session = await self._iam.session_user(session_id)
        conversation = await self._owned(session, conversation_id)
        resolved = message_id or uuid4()
        conversation.complete_assistant_message(
            resolved,
            clamp_content(content, self._options.max_assistant_chars),
            datetime.now(UTC),
            self._options.max_messages_per_conversation,
            self._options.max_assistant_chars,
            resources,
            tools,
            token_usage,
            interrupted,
        )
        if reasoning.strip():
            # Same unit of work as the completion, so a message never shows
            # thinking without the answer it belongs to.
            conversation.record_assistant_reasoning(
                resolved,
                reasoning,
                datetime.now(UTC),
                self._options.max_assistant_chars,
            )
        await self.save(conversation)
        self._log.info("conversation.message.assistant done", message_id=str(resolved))
        return MessageRef(message_id=resolved, conversation_id=conversation_id)

    async def start_run(
        self,
        session_id: UUID,
        conversation_id: UUID,
        message_id: UUID,
        run_id: UUID | None = None,
    ) -> RunRef:
        """Registers a running agent run that produces the given message."""
        session = await self._iam.session_user(session_id)
        conversation = await self._owned(session, conversation_id)
        resolved = run_id or uuid4()
        conversation.start_run(resolved, message_id, datetime.now(UTC))
        await self.save(conversation)
        return RunRef(run_id=resolved, conversation_id=conversation_id)

    async def request_approval(
        self,
        session_id: UUID,
        conversation_id: UUID,
        run_id: UUID,
        tool: str,
        args_hash: str,
        reason: str,
        approval_id: UUID | None = None,
    ) -> UUID:
        """Records a pending approval and returns its id."""
        session = await self._iam.session_user(session_id)
        conversation = await self._owned(session, conversation_id)
        resolved = approval_id or uuid4()
        conversation.request_approval(
            resolved,
            run_id,
            tool,
            args_hash,
            reason,
            datetime.now(UTC),
        )
        await self.save(conversation)
        self._log.info("conversation.approval.requested", approval_id=str(resolved))
        return resolved

    async def decide_approval(
        self,
        session_id: UUID,
        conversation_id: UUID,
        run_id: UUID,
        approval_id: UUID,
        approved: bool,
    ) -> None:
        """Records a human decision on a pending approval."""
        session = await self._iam.session_user(session_id)
        conversation = await self._owned(session, conversation_id)
        conversation.decide_approval(
            approval_id,
            run_id,
            approved,
            session.user_id,
            datetime.now(UTC),
        )
        await self.save(conversation)
        self._log.info(
            "conversation.approval.decided",
            approval_id=str(approval_id),
            approved=approved,
        )

    async def finish_run(
        self,
        session_id: UUID,
        conversation_id: UUID,
        run_id: UUID,
        status: RunStatus,
        error: str | None = None,
    ) -> None:
        """Moves a running run to a terminal status.

        The run status is what unblocks the conversation, so the write is retried
        when another command on the same conversation changed its version in
        between (a rename, a discard, a second message). A run somebody already
        finished is not an error: the caller only cares that it is no longer
        running.

        Args:
            session_id: Session the caller writes with.
            conversation_id: Conversation that owns the run.
            run_id: Run to finish.
            status: Terminal status.
            error: Failure message, or ``None``.

        Raises:
            UnknownRunError: If the conversation has no such run.
            RecordConflictError: If every attempt lost the version race.
        """
        session = await self._iam.session_user(session_id)
        for attempt in range(3):
            conversation = await self._owned(session, conversation_id)
            run = conversation.runs.get(run_id)
            if run is None:
                msg = f"run {run_id} does not exist in conversation {conversation_id}"
                raise UnknownRunError(msg)
            if run.status != "running":
                self._log.info(
                    "conversation.run.already_finished",
                    run_id=str(run_id),
                    status=run.status,
                )
                return
            conversation.finish_run(run_id, status, datetime.now(UTC), error)
            try:
                await self.save(conversation)
            except RecordConflictError:
                if attempt == 2:
                    raise
                self._log.info(
                    "conversation.run.conflict",
                    run_id=str(run_id),
                    attempt=attempt + 1,
                )
                await asyncio.sleep(0.05 * float(attempt + 1))
                continue
            self._log.info("conversation.run.finished", run_id=str(run_id), status=status)
            return

    async def discard_conversation(self, session_id: UUID, conversation_id: UUID) -> None:
        """Soft-deletes a conversation and hides its messages."""
        self._log.info("conversation.discard start", conversation_id=str(conversation_id))
        session = await self._iam.session_user(session_id)
        conversation = await self._owned(session, conversation_id)
        conversation.discard(session.user_id, datetime.now(UTC))
        await self.save(conversation)
        self._log.info("conversation.discard done", conversation_id=str(conversation_id))

    async def created_conversation_row(self, conversation_id: UUID) -> ConversationRow:
        """Returns the row of a just-created conversation from the aggregate.

        The create route cannot read its own write back from the read model: the
        projection may not have applied the event yet.

        Args:
            conversation_id: ID the create use case returned.

        Returns:
            The conversation row, built without the read model.
        """
        conversation = await self._conversation(conversation_id)
        return ConversationRow(
            conversation_id=conversation.id,
            user_id=conversation.user_id,
            tenant_id=conversation.tenant_id,
            title=conversation.title,
            status=conversation.status,
            active_llm_provider_id=conversation.active_llm_provider_id,
            message_count=conversation.message_count,
            run_count=len(conversation.runs),
            created_at=conversation.created_at,
            last_activity_at=conversation.last_activity_at,
        )

    # -- reads --------------------------------------------------------------

    async def list_conversations(
        self,
        session_id: UUID,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[ConversationRow]:
        """Returns the conversations of the caller, most recently active first."""
        session = await self._iam.session_user(session_id)
        size, start = self._page(limit, offset)
        return await self._view.list_conversations(
            session.user_id,
            session.tenant_id,
            limit=size,
            offset=start,
        )

    async def get_conversation(self, session_id: UUID, conversation_id: UUID) -> ConversationRow:
        """Returns one conversation of the caller."""
        session = await self._iam.session_user(session_id)
        row = await self._view.get_conversation(conversation_id)
        if row is None or not self._can_read(session, row):
            msg = f"conversation {conversation_id} does not exist"
            raise UnknownConversationError(msg)
        return row

    async def list_messages(
        self,
        session_id: UUID,
        conversation_id: UUID,
        limit: int | None = None,
        offset: int = 0,
        newest_first: bool = False,
    ) -> list[MessageRow]:
        """Returns the messages of a conversation the caller owns."""
        await self.get_conversation(session_id, conversation_id)
        size, start = self._page(limit, offset)
        return await self._view.list_messages(
            conversation_id,
            limit=size,
            offset=start,
            newest_first=newest_first,
        )

    async def get_run(self, session_id: UUID, run_id: UUID) -> RunRow:
        """Returns one run of a conversation the caller owns."""
        session = await self._iam.session_user(session_id)
        row = await self._view.get_run(run_id)
        if row is None:
            msg = f"run {run_id} does not exist"
            raise UnknownConversationError(msg)
        conversation = await self._view.get_conversation(row.conversation_id)
        if conversation is None or not self._can_read(session, conversation):
            msg = f"run {run_id} does not exist"
            raise UnknownConversationError(msg)
        return row

    async def list_runs(self, session_id: UUID, conversation_id: UUID) -> list[RunRow]:
        """Returns the runs of a conversation the caller owns."""
        await self.get_conversation(session_id, conversation_id)
        return await self._view.list_runs(conversation_id)

    async def list_pending_approvals(
        self,
        session_id: UUID,
        conversation_id: UUID,
    ) -> list[ApprovalRow]:
        """Returns the decisions a conversation still waits for.

        The age of the run does not matter: a paused run stays answerable until
        somebody decides, and the card is the only way back into it after a
        reload. Runs nothing can continue are closed by ``_ensure_no_running_run``
        instead, which removes their cards with them.
        """
        await self.get_conversation(session_id, conversation_id)
        return await self._view.list_pending_approvals(conversation_id)

    # -- internals ----------------------------------------------------------

    async def _conversation(self, conversation_id: UUID) -> Conversation:
        """Returns a live conversation aggregate, rejecting an unknown id."""
        try:
            conversation: Conversation = await self.repository.get(conversation_id)
        except AggregateNotFoundError as exc:
            msg = f"conversation {conversation_id} does not exist"
            raise UnknownConversationError(msg) from exc
        if conversation.is_discarded:
            msg = f"conversation {conversation_id} does not exist"
            raise UnknownConversationError(msg)
        return conversation

    async def _owned(self, session: SessionUser, conversation_id: UUID) -> Conversation:
        """Returns an aggregate the caller may change."""
        conversation = await self._conversation(conversation_id)
        if conversation.user_id == session.user_id or session.is_system_admin:
            return conversation
        msg = f"the caller may not change conversation {conversation_id}"
        raise PermissionDeniedError(msg)

    def _can_read(self, session: SessionUser, row: ConversationRow) -> bool:
        """Returns whether the caller may read the conversation."""
        return row.user_id == session.user_id or session.is_system_admin

    async def _ensure_no_running_run(self, conversation_id: UUID) -> None:
        """Rejects a new message while a run is still in flight.

        One conversation owns one *active* run, so a second run would race the
        first on the conversation aggregate and on the message it writes.
        Steering is therefore unsupported: the caller waits for the run to
        finish, or for the stale window to expire.

        A stale run that waits for no decision is abandoned here: nothing can
        continue it (the process that owned the stream is gone), so it must not
        hold the conversation. A stale run *with* a pending approval keeps it,
        because a human can still answer that card.

        Args:
            conversation_id: Conversation the message targets.

        Raises:
            RunInProgressError: If a fresh run is still running.
        """
        window = self._options.run_stale_after_seconds
        if window <= 0:
            return
        now = datetime.now(UTC)
        for run in await self._view.list_runs(conversation_id):
            if run.status != "running":
                continue
            started = run.started_at
            if started.tzinfo is None:
                started = started.replace(tzinfo=UTC)
            if (now - started).total_seconds() < window:
                msg = (
                    f"conversation {conversation_id} has a run in flight; steering is not supported"
                )
                raise RunInProgressError(msg)
            await self._abandon_stale(conversation_id, run.run_id)

    async def _abandon_stale(self, conversation_id: UUID, run_id: UUID) -> None:
        """Closes a run that nothing can continue any more.

        The check is best effort: a lost version race or a run somebody finished
        meanwhile is not an error, and a failure here must never block the new
        message.

        Args:
            conversation_id: Conversation that owns the run.
            run_id: Run the read model still reports as running.
        """
        try:
            conversation = await self._conversation(conversation_id)
            run = conversation.runs.get(run_id)
            if run is None or run.status != "running":
                return
            if any(approval.status == "pending" for approval in run.approvals.values()):
                return
            conversation.finish_run(
                run_id,
                "interrupted",
                datetime.now(UTC),
                "the run was abandoned after the stale window",
            )
            await self.save(conversation)
            self._log.info("conversation.run.abandoned", run_id=str(run_id))
        except InvalidRunTransitionError:
            return
        except Exception:
            self._log.exception("conversation.run.abandon.failed", run_id=str(run_id))

    def _page(self, limit: int | None, offset: int) -> tuple[int, int]:
        """Clamps a requested page to the configured bounds."""
        size = self._options.default_page_size if limit is None else limit
        return max(1, min(size, self._options.max_page_size)), max(0, offset)
