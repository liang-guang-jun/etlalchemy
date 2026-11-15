"""Result objects and observer port of the agent runtime."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol
from uuid import UUID

from etlalchemy.conversation.aggregates.types import (
    ResourceAccess,
    TokenUsage,
    ToolCallRecord,
)


@dataclass(frozen=True)
class ToolCall:
    """One tool call made during a run, with everything the trace needs."""

    tool: str
    """Name of the tool that was called."""
    args_hash: str
    """Stable digest of the arguments."""
    status: str = "ok"
    """Outcome of the call."""
    duration_ms: int = 0
    """Wall-clock duration of the call in milliseconds."""
    error_code: str | None = None
    """Bracketed error category, or ``None``."""
    args_json: str = ""
    """Redacted, truncated JSON of the arguments, for the tool drawer."""
    result_preview: str = ""
    """Truncated text the tool returned, for the tool drawer."""

    def as_record(self) -> ToolCallRecord:
        """Returns the conversation trace record of this call."""
        return ToolCallRecord(
            tool=self.tool,
            args_hash=self.args_hash,
            status=self.status,
            duration_ms=self.duration_ms,
            error_code=self.error_code,
            args_json=self.args_json,
            result_preview=self.result_preview,
        )


@dataclass(frozen=True)
class ApprovalRequest:
    """A destructive tool call waiting for a human decision."""

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


@dataclass(frozen=True)
class AgentRun:
    """Result of one agent execution."""

    run_id: UUID
    """ID of the run."""
    conversation_id: UUID
    """Conversation the run belongs to."""
    message_id: UUID
    """Assistant message the run produces."""
    status: str
    """One of ``completed``, ``failed``, ``interrupted`` or ``awaiting_approval``."""
    final_answer: str = ""
    """Text of the last assistant message."""
    reasoning: str = ""
    """Thinking the model streamed before its answer, possibly truncated."""
    tool_calls: list[ToolCall] = field(default_factory=list)
    """Every tool call of the run, in call order."""
    resources_accessed: list[ResourceAccess] = field(default_factory=list)
    """Every resource read of the run, in read order."""
    usage: TokenUsage = field(default_factory=TokenUsage)
    """Token accounting of the run."""
    approvals: list[ApprovalRequest] = field(default_factory=list)
    """Approvals the run requested."""
    error: str | None = None
    """Failure message of a failed run, or ``None``."""


class RunObserver(Protocol):
    """Receives the incremental progress of one run.

    The runtime only knows this port; the SSE streamer implements it. Every
    method is a coroutine so a slow consumer applies back pressure to the run.
    """

    async def message_started(self, *, run_id: UUID, message_id: UUID) -> None:
        """Records that the run started producing its assistant message."""
        ...

    async def token(self, *, run_id: UUID, delta: str) -> None:
        """Records one streamed model token."""
        ...

    async def reasoning(self, *, run_id: UUID, delta: str) -> None:
        """Records one streamed chunk of the model's thinking."""
        ...

    async def tool_started(self, *, run_id: UUID, call: ToolCall) -> None:
        """Records that a tool call started."""
        ...

    async def tool_finished(self, *, run_id: UUID, call: ToolCall) -> None:
        """Records that a tool call finished."""
        ...

    async def resource_read(self, *, run_id: UUID, access: ResourceAccess) -> None:
        """Records that a resource was read."""
        ...

    async def approval_required(
        self,
        *,
        run_id: UUID,
        approval: ApprovalRequest,
    ) -> None:
        """Records that the run is blocked on a human decision."""
        ...

    async def approval_resolved(
        self,
        *,
        run_id: UUID,
        approval_id: UUID,
        approved: bool,
    ) -> None:
        """Records that a pending approval was decided."""
        ...

    async def message_completed(self, *, run: AgentRun) -> None:
        """Records that the assistant message was persisted."""
        ...

    async def failed(self, *, run_id: UUID, error: str) -> None:
        """Records that the run failed."""
        ...
