"""Read model interface of the conversation context."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

from eventsourcing.asyncio.persistence import AsyncTrackingRecorder
from eventsourcing.persistence import Tracking


def as_uuid(value: UUID | str) -> UUID:
    """Returns the given value as a :class:`UUID`."""
    return value if isinstance(value, UUID) else UUID(value)


@dataclass(frozen=True)
class ResourceAccessRow:
    """One resource read recorded on a message."""

    uri: str
    """URI of the resource that was read."""
    size_bytes: int = 0
    """Size of the returned payload in bytes."""
    mime_type: str = ""
    """MIME type of the returned payload."""
    read_at: datetime | None = None
    """Moment the resource was read, or ``None``."""


@dataclass(frozen=True)
class ToolCallRow:
    """One tool call recorded on a message."""

    tool: str
    """Name of the tool that was called."""
    args_hash: str = ""
    """Stable digest of the arguments."""
    status: str = "ok"
    """Outcome of the call."""
    duration_ms: int = 0
    """Wall-clock duration of the call in milliseconds."""
    error_code: str | None = None
    """Bracketed error category the tool reported, or ``None``."""
    args_json: str = ""
    """Redacted, truncated JSON of the arguments."""
    result_preview: str = ""
    """Truncated text the tool returned."""


@dataclass(frozen=True)
class MessageRow:
    """One message of a conversation as stored in the read model."""

    message_id: UUID
    """ID of the message."""
    conversation_id: UUID
    """ID of the conversation that owns the message."""
    role: str
    """Author of the message."""
    content: str
    """Body of the message."""
    interrupted: bool
    """Whether the stream that produced the message was interrupted."""
    input_tokens: int
    """Prompt tokens billed by the provider."""
    output_tokens: int
    """Completion tokens billed by the provider."""
    created_at: datetime
    """Moment the message was written."""
    resources: list[ResourceAccessRow] = field(default_factory=list)
    """Resources read while producing the message."""
    tools: list[ToolCallRow] = field(default_factory=list)
    """Tool calls made while producing the message."""
    reasoning: str = ""
    """Thinking the model streamed before its answer."""


@dataclass(frozen=True)
class ApprovalRow:
    """One approval of an agent run."""

    approval_id: UUID
    """ID of the approval."""
    run_id: UUID
    """Run that asked for the decision."""
    conversation_id: UUID
    """Conversation that owns the run."""
    tool: str
    """Tool that is waiting for the decision."""
    args_hash: str
    """Digest of the arguments the tool was called with."""
    reason: str
    """Reason shown to the approver."""
    status: str
    """One of ``pending``, ``approved`` or ``denied``."""
    requested_at: datetime
    """Moment the decision was requested."""
    decided_by: UUID | None = None
    """User that decided, or ``None`` while pending."""
    decided_at: datetime | None = None
    """Moment of the decision, or ``None`` while pending."""


@dataclass(frozen=True)
class RunRow:
    """One agent run as stored in the read model."""

    run_id: UUID
    """ID of the run."""
    conversation_id: UUID
    """Conversation that owns the run."""
    message_id: UUID
    """Assistant message the run produces."""
    status: str
    """One of ``running``, ``completed``, ``failed`` or ``interrupted``."""
    started_at: datetime
    """Moment the run started."""
    finished_at: datetime | None = None
    """Moment the run finished, or ``None`` while running."""
    error: str | None = None
    """Failure message of a failed run, or ``None``."""
    approvals: list[ApprovalRow] = field(default_factory=list)
    """Decisions requested by the run, in request order."""


@dataclass(frozen=True)
class ConversationRow:
    """One conversation as stored in the read model."""

    conversation_id: UUID
    """ID of the conversation aggregate."""
    user_id: UUID
    """User the conversation belongs to."""
    tenant_id: UUID | None
    """Tenant the conversation belongs to, or ``None``."""
    title: str
    """Conversation title."""
    status: str
    """One of ``OPEN`` or ``DISCARDED``."""
    active_llm_provider_id: UUID | None
    """LLM provider selected for the conversation, or ``None``."""
    message_count: int
    """Number of stored messages."""
    run_count: int
    """Number of agent runs."""
    created_at: datetime
    """Moment the conversation was created."""
    last_activity_at: datetime
    """Moment of the last message, run or approval change."""
    discarded_at: datetime | None = None
    """Moment of the soft delete, or ``None`` while the conversation is live."""


class ConversationView(AsyncTrackingRecorder, ABC):
    """Read model of the conversation context."""

    @abstractmethod
    async def create_table(self) -> None:
        """Creates the tracking table and the view tables if they do not exist."""

    # -- writes -------------------------------------------------------------

    @abstractmethod
    async def register_conversation(
        self,
        conversation_id: UUID,
        user_id: UUID,
        tenant_id: UUID | None,
        title: str,
        active_llm_provider_id: UUID | None,
        created_at: datetime,
        tracking: Tracking,
    ) -> None:
        """Registers a conversation, clearing a previous discarded marker."""

    @abstractmethod
    async def rename_conversation(
        self,
        conversation_id: UUID,
        title: str,
        tracking: Tracking,
    ) -> None:
        """Changes the title of a conversation."""

    @abstractmethod
    async def switch_provider(
        self,
        conversation_id: UUID,
        provider_id: UUID | None,
        tracking: Tracking,
    ) -> None:
        """Changes the LLM provider a conversation uses."""

    @abstractmethod
    async def append_message(
        self,
        message_id: UUID,
        conversation_id: UUID,
        role: str,
        content: str,
        created_at: datetime,
        tracking: Tracking,
    ) -> None:
        """Registers a message without a trace and bumps the activity pointer."""

    @abstractmethod
    async def edit_message(
        self,
        conversation_id: UUID,
        message_id: UUID,
        content: str,
        removed_message_ids: tuple[UUID, ...],
        removed_run_ids: tuple[UUID, ...],
        edited_at: datetime,
        tracking: Tracking,
    ) -> None:
        """Rewrites a user message and hides its successors."""

    @abstractmethod
    async def complete_message(
        self,
        message_id: UUID,
        conversation_id: UUID,
        role: str,
        content: str,
        interrupted: bool,
        input_tokens: int,
        output_tokens: int,
        resources: list[ResourceAccessRow],
        tools: list[ToolCallRow],
        created_at: datetime,
        tracking: Tracking,
    ) -> None:
        """Registers an assistant message with its whole trace."""

    @abstractmethod
    async def record_reasoning(
        self,
        message_id: UUID,
        reasoning: str,
        tracking: Tracking,
    ) -> None:
        """Stores the thinking of an already registered assistant message."""

    @abstractmethod
    async def start_run(
        self,
        run_id: UUID,
        conversation_id: UUID,
        message_id: UUID,
        started_at: datetime,
        tracking: Tracking,
    ) -> None:
        """Registers a running agent run."""

    @abstractmethod
    async def request_approval(
        self,
        approval_id: UUID,
        run_id: UUID,
        conversation_id: UUID,
        tool: str,
        args_hash: str,
        reason: str,
        requested_at: datetime,
        tracking: Tracking,
    ) -> None:
        """Registers a pending approval."""

    @abstractmethod
    async def decide_approval(
        self,
        approval_id: UUID,
        approved: bool,
        decided_by: UUID,
        decided_at: datetime,
        tracking: Tracking,
    ) -> None:
        """Finalises a pending approval."""

    @abstractmethod
    async def finish_run(
        self,
        run_id: UUID,
        status: str,
        finished_at: datetime,
        error: str | None,
        tracking: Tracking,
    ) -> None:
        """Finalises a run."""

    @abstractmethod
    async def discard_conversation(
        self,
        conversation_id: UUID,
        discarded_at: datetime,
        tracking: Tracking,
    ) -> None:
        """Soft-deletes a conversation and cascades to its messages and runs."""

    # -- reads --------------------------------------------------------------

    @abstractmethod
    async def get_conversation(self, conversation_id: UUID) -> ConversationRow | None:
        """Returns a live conversation, or ``None``."""

    @abstractmethod
    async def list_conversations(
        self,
        user_id: UUID,
        tenant_id: UUID | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[ConversationRow]:
        """Returns live conversations of a user, most recently active first."""

    @abstractmethod
    async def list_messages(
        self,
        conversation_id: UUID,
        limit: int | None = None,
        offset: int = 0,
        newest_first: bool = False,
    ) -> list[MessageRow]:
        """Returns the live messages of a conversation, oldest or newest first.

        ``newest_first`` windows from the end of the conversation, which is what a
        replayed history needs; the returned rows are always in chronological
        order.
        """

    @abstractmethod
    async def get_message(self, message_id: UUID) -> MessageRow | None:
        """Returns one message, or ``None``."""

    @abstractmethod
    async def count_messages(self, conversation_id: UUID) -> int:
        """Returns the number of live messages of a conversation."""

    @abstractmethod
    async def get_run(self, run_id: UUID) -> RunRow | None:
        """Returns one run with its approvals, or ``None``."""

    @abstractmethod
    async def list_runs(self, conversation_id: UUID) -> list[RunRow]:
        """Returns the runs of a conversation in start order."""

    @abstractmethod
    async def list_pending_approvals(self, conversation_id: UUID) -> list[ApprovalRow]:
        """Returns the approvals of a conversation that still wait for a decision."""
