"""Conversation aggregate: one agent thread with its messages and runs."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from uuid import UUID

from eventsourcing.domain import Aggregate, AggregateCreated, event

from etlalchemy.conversation.aggregates.errors import (
    ApprovalAlreadyDecidedError,
    ConversationFullError,
    DiscardedError,
    DuplicateMessageError,
    DuplicateRunError,
    InvalidRunTransitionError,
    MessageEmptyError,
    MessageTooLongError,
    RunInProgressError,
    UnknownApprovalError,
    UnknownMessageError,
    UnknownRunError,
)
from etlalchemy.conversation.aggregates.types import (
    MAX_TITLE_LENGTH,
    ApprovalStatus,
    MessageRole,
    ResourceAccess,
    RunStatus,
    TokenUsage,
    ToolCallRecord,
    clamp_content,
    normalise_title,
)

Resources = tuple[ResourceAccess, ...]
"""Resources read by one assistant message, in read order."""

ToolCalls = tuple[ToolCallRecord, ...]
"""Tool calls made by one assistant message, in call order."""


@dataclass(frozen=True)
class Message:
    """One message of a conversation."""

    message_id: UUID
    """ID of the message."""
    role: MessageRole
    """Author of the message."""
    content: str
    """Body of the message, possibly truncated."""
    created_at: datetime
    """Moment the message was written."""
    resources: Resources = ()
    """Resources read while producing the message."""
    tools: ToolCalls = ()
    """Tool calls made while producing the message."""
    token_usage: TokenUsage = field(default_factory=TokenUsage)
    """Token accounting of an assistant message."""
    interrupted: bool = False
    """Whether the stream that produced the message was interrupted."""
    reasoning: str = ""
    """Thinking the model streamed before its answer, possibly truncated."""


@dataclass(frozen=True)
class Approval:
    """One human-in-the-loop decision requested by a destructive tool call."""

    approval_id: UUID
    """ID of the approval."""
    run_id: UUID
    """Run that asked for the decision."""
    tool: str
    """Tool that is waiting for the decision."""
    args_hash: str
    """Digest of the arguments the tool was called with."""
    reason: str
    """Human-readable reason shown to the approver."""
    status: ApprovalStatus
    """Current state of the approval."""
    requested_at: datetime
    """Moment the decision was requested."""
    decided_by: UUID | None = None
    """User that decided, or ``None`` while pending."""
    decided_at: datetime | None = None
    """Moment of the decision, or ``None`` while pending."""


@dataclass(frozen=True)
class Run:
    """One agent execution inside a conversation."""

    run_id: UUID
    """ID of the run."""
    message_id: UUID
    """Assistant message the run produces."""
    started_at: datetime
    """Moment the run started."""
    status: RunStatus
    """Current status of the run."""
    finished_at: datetime | None = None
    """Moment the run finished, or ``None`` while running."""
    error: str | None = None
    """Failure message of a failed run, or ``None``."""
    approvals: dict[UUID, Approval] = field(default_factory=dict)
    """Decisions requested by the run, keyed by approval id."""


class Conversation(Aggregate):
    """Aggregate root that owns the messages and runs of one agent thread.

    The aggregate is the single source of truth for a conversation: the user
    message is recorded before the stream starts and the assistant message when
    it ends, so an interrupted run still leaves a truthful history. Runs and
    their approvals are internal entities, keyed by id.
    """

    def __init__(
        self,
        user_id: UUID,
        tenant_id: UUID | None,
        created_at: datetime,
        title: str = "",
        active_llm_provider_id: UUID | None = None,
    ) -> None:
        """Initialises an empty, open conversation."""
        self.user_id = user_id
        self.tenant_id = tenant_id
        self.title = normalise_title(title)
        self.status: str = "OPEN"
        self.active_llm_provider_id = active_llm_provider_id
        self.created_at = created_at
        self.last_activity_at = created_at
        self.discarded_at: datetime | None = None
        self.messages: dict[UUID, Message] = {}
        self.runs: dict[UUID, Run] = {}

    class Event(Aggregate.Event):
        """Base class for events raised by the conversation aggregate."""

    @dataclass(frozen=True)
    class Started(AggregateCreated):
        """Recorded when a conversation is created."""

        user_id: UUID
        """User the conversation belongs to."""
        tenant_id: UUID | None
        """Tenant the conversation belongs to, or ``None``."""
        created_at: datetime
        """Moment the conversation was created."""
        title: str = ""
        """Optional conversation title."""
        active_llm_provider_id: UUID | None = None
        """LLM provider selected for the conversation, or ``None``."""

        def __post_init__(self) -> None:
            """Normalises the decoded title."""
            object.__setattr__(self, "title", normalise_title(self.title))

    @dataclass(frozen=True)
    class Renamed(Event):
        """Recorded when the conversation title changes."""

        title: str
        """New, validated title."""

        def __post_init__(self) -> None:
            """Normalises the decoded title."""
            object.__setattr__(self, "title", normalise_title(self.title))

    @dataclass(frozen=True)
    class ProviderSwitched(Event):
        """Recorded when the conversation selects another LLM provider."""

        provider_id: UUID | None
        """New provider, or ``None`` to fall back to the default chain."""

    @dataclass(frozen=True)
    class UserMessageAppended(Event):
        """Recorded when a user message is accepted."""

        message_id: UUID
        """ID of the message."""
        content: str
        """Body of the message."""
        created_at: datetime
        """Moment the message was written."""

    @dataclass(frozen=True)
    class UserMessageEdited(Event):
        """Recorded when a user message is rewritten.

        The event also carries every message and run that followed it: the
        aggregate drops them in the same unit of work, so an edited prompt
        cannot leave an answer that belongs to the old text behind.
        """

        message_id: UUID
        """ID of the edited message."""
        content: str
        """New body of the message."""
        removed_message_ids: tuple[UUID, ...]
        """Messages that followed the edited one and were dropped."""
        removed_run_ids: tuple[UUID, ...]
        """Runs whose assistant message was dropped."""
        edited_at: datetime
        """Moment the message was edited."""

        def __post_init__(self) -> None:
            """Normalises the decoded id lists into tuples."""
            object.__setattr__(self, "removed_message_ids", tuple(self.removed_message_ids))
            object.__setattr__(self, "removed_run_ids", tuple(self.removed_run_ids))

    @dataclass(frozen=True)
    class AssistantMessageCompleted(Event):
        """Recorded when the assistant finishes a message, with its whole trace."""

        message_id: UUID
        """ID of the message."""
        content: str
        """Body of the message, possibly truncated."""
        resources: Resources
        """Resources read while producing the message."""
        tools: ToolCalls
        """Tool calls made while producing the message."""
        token_usage: TokenUsage
        """Token accounting of the message."""
        interrupted: bool
        """Whether the stream that produced the message was interrupted."""
        created_at: datetime
        """Moment the message was completed."""

        def __post_init__(self) -> None:
            """Normalises the decoded trace lists into tuples."""
            object.__setattr__(self, "resources", tuple(self.resources))
            object.__setattr__(self, "tools", tuple(self.tools))

    @dataclass(frozen=True)
    class AssistantMessageReasoned(Event):
        """Recorded when the thinking of an assistant message is kept.

        The reasoning travels in its own event because adding a field to
        :class:`AssistantMessageCompleted` would break the replay of the
        messages stored before it existed.
        """

        message_id: UUID
        """ID of the assistant message."""
        reasoning: str
        """Thinking the model streamed, possibly truncated."""
        created_at: datetime
        """Moment the reasoning was recorded."""

    @dataclass(frozen=True)
    class RunStarted(Event):
        """Recorded when an agent run starts."""

        run_id: UUID
        """ID of the run."""
        message_id: UUID
        """Assistant message the run produces."""
        started_at: datetime
        """Moment the run started."""

    @dataclass(frozen=True)
    class ApprovalRequested(Event):
        """Recorded when a destructive tool call needs a human decision."""

        approval_id: UUID
        """ID of the approval."""
        run_id: UUID
        """Run that asks for the decision."""
        tool: str
        """Tool waiting for the decision."""
        args_hash: str
        """Digest of the arguments the tool was called with."""
        reason: str
        """Reason shown to the approver."""
        requested_at: datetime
        """Moment the decision was requested."""

    @dataclass(frozen=True)
    class ApprovalDecided(Event):
        """Recorded when a pending approval is decided."""

        approval_id: UUID
        """ID of the approval."""
        run_id: UUID
        """Run that asked for the decision."""
        approved: bool
        """Whether the tool call may run."""
        decided_by: UUID
        """User that decided."""
        decided_at: datetime
        """Moment of the decision."""

    @dataclass(frozen=True)
    class RunFinished(Event):
        """Recorded when an agent run reaches a terminal status."""

        run_id: UUID
        """ID of the run."""
        status: RunStatus
        """Terminal status of the run."""
        finished_at: datetime
        """Moment the run finished."""
        error: str | None = None
        """Failure message of a failed run, or ``None``."""

    @dataclass(frozen=True)
    class Discarded(Event):
        """Recorded when the conversation is discarded."""

        by_user_id: UUID
        """User that discarded the conversation."""
        at: datetime
        """Moment of the soft delete."""

    # -- commands -----------------------------------------------------------

    @event(Renamed)
    def rename(self, title: str) -> None:
        """Changes the conversation title."""
        self._ensure_not_discarded()
        cleaned = normalise_title(title)
        if len(cleaned) > MAX_TITLE_LENGTH:
            msg = f"a conversation title must not exceed {MAX_TITLE_LENGTH} characters"
            raise MessageTooLongError(msg)
        self.title = cleaned

    @event(ProviderSwitched)
    def switch_provider(self, provider_id: UUID | None) -> None:
        """Selects the LLM provider used by the next message of the conversation."""
        self._ensure_not_discarded()
        self.active_llm_provider_id = provider_id

    def append_user_message(
        self,
        message_id: UUID,
        content: str,
        created_at: datetime,
        max_messages: int,
        max_chars: int,
    ) -> None:
        """Records a user message before the run that answers it starts."""
        self._ensure_not_discarded()
        self._ensure_new_message(message_id, max_messages)
        cleaned = self._checked_content(content, max_chars)
        self._user_message_appended(message_id, cleaned, created_at)

    def edit_user_message(
        self,
        message_id: UUID,
        content: str,
        edited_at: datetime,
        max_chars: int,
    ) -> None:
        """Rewrites a user message and drops every message that followed it.

        Args:
            message_id: User message to rewrite.
            content: New body of the message.
            edited_at: Moment of the edit.
            max_chars: Maximum length of the body.

        Raises:
            DiscardedError: When the conversation is discarded.
            UnknownMessageError: When the id is not a user message.
            RunInProgressError: When a run of the conversation is still running.
            MessageEmptyError: When the new body is blank.
            MessageTooLongError: When the new body exceeds ``max_chars``.
        """
        self._ensure_not_discarded()
        message = self.messages.get(message_id)
        if message is None or message.role != "user":
            msg = f"message {message_id} is not a user message of conversation {self.id}"
            raise UnknownMessageError(msg)
        if any(run.status == "running" for run in self.runs.values()):
            msg = "a message cannot be edited while a run is in progress"
            raise RunInProgressError(msg)
        cleaned = self._checked_content(content, max_chars)
        ordered = list(self.messages)
        removed_messages = tuple(ordered[ordered.index(message_id) + 1 :])
        removed_runs = tuple(
            run_id for run_id, run in self.runs.items() if run.message_id in removed_messages
        )
        self._user_message_edited(
            message_id,
            cleaned,
            removed_messages,
            removed_runs,
            edited_at,
        )

    @event(UserMessageEdited)
    def _user_message_edited(
        self,
        message_id: UUID,
        content: str,
        removed_message_ids: tuple[UUID, ...],
        removed_run_ids: tuple[UUID, ...],
        edited_at: datetime,
    ) -> None:
        """Applies a user-message edit and drops its successors."""
        self.messages[message_id] = replace(self.messages[message_id], content=content)
        for removed in removed_message_ids:
            self.messages.pop(removed, None)
        for run_id in removed_run_ids:
            self.runs.pop(run_id, None)
        self.last_activity_at = edited_at

    def complete_assistant_message(
        self,
        message_id: UUID,
        content: str,
        created_at: datetime,
        max_messages: int,
        max_chars: int,
        resources: Resources = (),
        tools: ToolCalls = (),
        token_usage: TokenUsage | None = None,
        interrupted: bool = False,
    ) -> None:
        """Records the assistant answer together with its whole trace."""
        self._ensure_not_discarded()
        self._ensure_new_message(message_id, max_messages)
        cleaned = clamp_content(content, max_chars)
        self._assistant_message_completed(
            message_id,
            cleaned,
            tuple(resources),
            tuple(tools),
            TokenUsage() if token_usage is None else token_usage,
            interrupted,
            created_at,
        )

    def record_assistant_reasoning(
        self,
        message_id: UUID,
        reasoning: str,
        created_at: datetime,
        max_chars: int,
    ) -> None:
        """Keeps the thinking that produced an assistant message.

        Args:
            message_id: ID of the assistant message.
            reasoning: Thinking the model streamed.
            created_at: Moment the reasoning is recorded.
            max_chars: Maximum length kept, or ``0`` for no limit.

        Raises:
            DiscardedError: When the conversation is discarded.
            UnknownMessageError: When the message is not an assistant message.
        """
        self._ensure_not_discarded()
        message = self.messages.get(message_id)
        if message is None or message.role != "assistant":
            msg = f"message {message_id} is not an assistant message of conversation {self.id}"
            raise UnknownMessageError(msg)
        self._assistant_message_reasoned(
            message_id,
            clamp_content(reasoning, max_chars),
            created_at,
        )

    @event(RunStarted)
    def start_run(self, run_id: UUID, message_id: UUID, started_at: datetime) -> None:
        """Registers a new running agent run."""
        self._ensure_not_discarded()
        if run_id in self.runs:
            msg = f"run {run_id} already exists in conversation {self.id}"
            raise DuplicateRunError(msg)
        self.runs[run_id] = Run(
            run_id=run_id,
            message_id=message_id,
            started_at=started_at,
            status="running",
        )
        self.last_activity_at = started_at

    @event(ApprovalRequested)
    def request_approval(
        self,
        approval_id: UUID,
        run_id: UUID,
        tool: str,
        args_hash: str,
        reason: str,
        requested_at: datetime,
    ) -> None:
        """Registers a pending approval on a running run."""
        self._ensure_not_discarded()
        run = self.run_of(run_id)
        if run.status != "running":
            msg = f"run {run_id} is {run.status} and cannot request an approval"
            raise InvalidRunTransitionError(msg)
        if approval_id in run.approvals:
            msg = f"approval {approval_id} already exists on run {run_id}"
            raise ApprovalAlreadyDecidedError(msg)
        self.runs[run_id] = replace(
            run,
            approvals={
                **run.approvals,
                approval_id: Approval(
                    approval_id=approval_id,
                    run_id=run_id,
                    tool=tool,
                    args_hash=args_hash,
                    reason=reason,
                    status="pending",
                    requested_at=requested_at,
                ),
            },
        )
        self.last_activity_at = requested_at

    @event(ApprovalDecided)
    def decide_approval(
        self,
        approval_id: UUID,
        run_id: UUID,
        approved: bool,
        decided_by: UUID,
        decided_at: datetime,
    ) -> None:
        """Records the human decision of a pending approval."""
        self._ensure_not_discarded()
        run = self.run_of(run_id)
        approval = run.approvals.get(approval_id)
        if approval is None:
            msg = f"approval {approval_id} does not exist on run {run_id}"
            raise UnknownApprovalError(msg)
        if approval.status != "pending":
            msg = f"approval {approval_id} is already {approval.status}"
            raise ApprovalAlreadyDecidedError(msg)
        self.runs[run_id] = replace(
            run,
            approvals={
                **run.approvals,
                approval_id: replace(
                    approval,
                    status="approved" if approved else "denied",
                    decided_by=decided_by,
                    decided_at=decided_at,
                ),
            },
        )
        self.last_activity_at = decided_at

    @event(RunFinished)
    def finish_run(
        self,
        run_id: UUID,
        status: RunStatus,
        finished_at: datetime,
        error: str | None = None,
    ) -> None:
        """Moves a running run to a terminal status."""
        self._ensure_not_discarded()
        run = self.run_of(run_id)
        if run.status != "running":
            msg = f"run {run_id} is already {run.status}"
            raise InvalidRunTransitionError(msg)
        if status == "running":
            msg = "a finished run cannot be running"
            raise InvalidRunTransitionError(msg)
        self.runs[run_id] = replace(
            run,
            status=status,
            finished_at=finished_at,
            error=error,
        )
        self.last_activity_at = finished_at

    @event(Discarded)
    def discard(self, by_user_id: UUID, at: datetime) -> None:
        """Soft-deletes the conversation and hides its messages and runs."""
        self._ensure_not_discarded()
        self.status = "DISCARDED"
        self.discarded_at = at
        self.last_activity_at = at

    # -- queries ------------------------------------------------------------

    @property
    def is_discarded(self) -> bool:
        """Returns whether the conversation has been discarded."""
        return self.discarded_at is not None

    @property
    def message_count(self) -> int:
        """Returns the number of stored messages."""
        return len(self.messages)

    def message_of(self, message_id: UUID) -> Message:
        """Returns one message, rejecting an unknown id."""
        message = self.messages.get(message_id)
        if message is None:
            msg = f"message {message_id} does not exist in conversation {self.id}"
            raise UnknownMessageError(msg)
        return message

    def run_of(self, run_id: UUID) -> Run:
        """Returns one run, rejecting an unknown id."""
        run = self.runs.get(run_id)
        if run is None:
            msg = f"run {run_id} does not exist in conversation {self.id}"
            raise UnknownRunError(msg)
        return run

    def approval_of(self, run_id: UUID, approval_id: UUID) -> Approval:
        """Returns one approval of a run, rejecting an unknown id."""
        approval = self.run_of(run_id).approvals.get(approval_id)
        if approval is None:
            msg = f"approval {approval_id} does not exist on run {run_id}"
            raise UnknownApprovalError(msg)
        return approval

    # -- event bodies -------------------------------------------------------

    @event(UserMessageAppended)
    def _user_message_appended(
        self,
        message_id: UUID,
        content: str,
        created_at: datetime,
    ) -> None:
        """Stores the user message."""
        self.messages[message_id] = Message(
            message_id=message_id,
            role="user",
            content=content,
            created_at=created_at,
        )
        self.last_activity_at = created_at

    # -- event bodies -------------------------------------------------------

    @event(AssistantMessageCompleted)
    def _assistant_message_completed(
        self,
        message_id: UUID,
        content: str,
        resources: Resources,
        tools: ToolCalls,
        token_usage: TokenUsage,
        interrupted: bool,
        created_at: datetime,
    ) -> None:
        """Stores the assistant message with its trace."""
        self.messages[message_id] = Message(
            message_id=message_id,
            role="assistant",
            content=content,
            created_at=created_at,
            resources=resources,
            tools=tools,
            token_usage=token_usage,
            interrupted=interrupted,
        )
        self.last_activity_at = created_at

    @event(AssistantMessageReasoned)
    def _assistant_message_reasoned(
        self,
        message_id: UUID,
        reasoning: str,
        created_at: datetime,
    ) -> None:
        """Stores the thinking of an assistant message."""
        self.messages[message_id] = replace(
            self.messages[message_id],
            reasoning=reasoning,
        )
        self.last_activity_at = created_at

    # -- validation ---------------------------------------------------------

    def _ensure_not_discarded(self) -> None:
        """Raises DiscardedError when the conversation has been discarded."""
        if self.is_discarded:
            msg = "conversation is discarded"
            raise DiscardedError(msg)

    def _ensure_new_message(self, message_id: UUID, max_messages: int) -> None:
        """Rejects a duplicate message id or a conversation that is already full."""
        if message_id in self.messages:
            msg = f"message {message_id} already exists in conversation {self.id}"
            raise DuplicateMessageError(msg)
        if len(self.messages) >= max_messages:
            msg = f"conversation {self.id} already holds {max_messages} messages"
            raise ConversationFullError(msg)

    def _checked_content(self, content: str, max_chars: int) -> str:
        """Rejects a blank or over-long message body."""
        cleaned = content.strip()
        if not cleaned:
            msg = "a message body must not be blank"
            raise MessageEmptyError(msg)
        if max_chars > 0 and len(cleaned) > max_chars:
            msg = f"a message body must not exceed {max_chars} characters"
            raise MessageTooLongError(msg)
        return cleaned
