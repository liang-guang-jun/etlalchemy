"""Server-sent events for one agent run.

The streamer is the run's observer: every token, tool call, resource read and
approval becomes one event with a monotonic ``seq``. Events are buffered per run,
so a client that reconnects with ``Last-Event-ID`` receives everything it missed;
the buffer is per process, which the contract documents.
"""

from __future__ import annotations

import asyncio
import json
from collections import deque
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from etlalchemy.agent.results import AgentRun, ApprovalRequest, ToolCall
from etlalchemy.conversation.aggregates.types import ResourceAccess

BUFFER_SIZE = 1000
"""Number of events kept for a replay of one run."""

HEARTBEAT_SECONDS = 15.0
"""Interval of the ``: ping`` comment that keeps proxies from closing the stream."""


@dataclass(frozen=True)
class SseEvent:
    """One server-sent event."""

    kind: str
    """Event name, for example ``tool.finished``."""
    seq: int
    """Monotonic sequence number inside one run, starting at 1."""
    run_id: UUID
    """Run the event belongs to."""
    timestamp: datetime
    """Moment the event was produced."""
    message_id: UUID | None = None
    """Assistant message the event belongs to, when known."""
    data: dict[str, Any] = field(default_factory=dict)
    """Event payload, merged into the ``data`` object."""

    def encode(self) -> str:
        """Renders the event as an SSE frame."""
        payload: dict[str, Any] = {
            "run_id": str(self.run_id),
            "seq": self.seq,
            "timestamp": self.timestamp.isoformat(),
        }
        if self.message_id is not None:
            payload["message_id"] = str(self.message_id)
        payload.update(self.data)
        body = json.dumps(payload, ensure_ascii=False, default=str)
        return f"id: {self.seq}\nevent: {self.kind}\ndata: {body}\n\n"


class RunStream:
    """Turns the progress of one run into SSE events and replays them."""

    def __init__(
        self,
        run_id: UUID,
        message_id: UUID | None = None,
        *,
        buffer_size: int = BUFFER_SIZE,
    ) -> None:
        """Starts an empty stream for the given run."""
        self.run_id = run_id
        self.message_id = message_id
        self._events: deque[SseEvent] = deque(maxlen=buffer_size)
        self._buffer_size = buffer_size
        self._dropped = 0
        self._seq = 0
        self._subscribers: list[asyncio.Queue[SseEvent | None]] = []
        self._closed = False

    @property
    def closed(self) -> bool:
        """Returns whether the stream already emitted its terminal event."""
        return self._closed

    @property
    def last_seq(self) -> int:
        """Returns the sequence number of the last emitted event."""
        return self._seq

    async def emit(self, kind: str, data: dict[str, Any] | None = None) -> SseEvent:
        """Appends one event and wakes every subscriber.

        Args:
            kind: Event name.
            data: Event payload.

        Returns:
            The stored event, with its assigned sequence number.
        """
        event = self._record(kind, data)
        for queue in list(self._subscribers):
            queue.put_nowait(event)
        if self._closed:
            for queue in list(self._subscribers):
                queue.put_nowait(None)
        return event

    def _record(self, kind: str, data: dict[str, Any] | None = None) -> SseEvent:
        """Assigns the next sequence number and buffers one event.

        Recording is synchronous on purpose: a reader that registers itself
        before it snapshots the buffer can never miss an event, because no await
        can interleave between the snapshot and the registration.
        """
        self._seq += 1
        event = SseEvent(
            kind=kind,
            seq=self._seq,
            run_id=self.run_id,
            timestamp=datetime.now(UTC),
            message_id=self.message_id,
            data=data or {},
        )
        if len(self._events) == self._buffer_size:
            self._dropped += 1
        self._events.append(event)
        if kind in {"done", "error"}:
            self._closed = True
        return event

    def replay(self, after_seq: int = 0) -> list[SseEvent]:
        """Returns the buffered events with a higher sequence number."""
        return [event for event in self._events if event.seq > after_seq]

    def metrics(self) -> dict[str, int | bool]:
        """Returns the per-process counters of this stream.

        ``dropped`` counts the events evicted from the replay buffer, which is
        the number a client cannot recover with ``Last-Event-ID`` on this
        process; the history endpoint is the fallback.

        Returns:
            Counters safe to log or expose on a metrics endpoint.
        """
        return {
            "events": self._seq,
            "buffered": len(self._events),
            "dropped": self._dropped,
            "subscribers": len(self._subscribers),
            "closed": self._closed,
        }

    async def events(
        self,
        after_seq: int = 0,
        *,
        heartbeat_seconds: float = HEARTBEAT_SECONDS,
    ) -> AsyncIterator[str]:
        """Yields SSE frames until the run emits its terminal event.

        Args:
            after_seq: Highest sequence number the client already received.
            heartbeat_seconds: Idle interval after which a ``: ping`` is sent.

        Yields:
            Encoded SSE frames.
        """
        queue: asyncio.Queue[SseEvent | None] = asyncio.Queue()
        # Register before the snapshot: an event recorded between the two would
        # otherwise be buffered but never delivered.
        self._subscribers.append(queue)
        try:
            high = after_seq
            for event in self.replay(after_seq):
                high = max(high, event.seq)
                yield event.encode()
            while True:
                try:
                    item = queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
                if item is None:
                    return
                if item.seq <= high:
                    continue
                high = item.seq
                yield item.encode()
            if self._closed:
                return
            while True:
                try:
                    item = await asyncio.wait_for(queue.get(), timeout=heartbeat_seconds)
                except TimeoutError:
                    yield ": ping\n\n"
                    continue
                if item is None:
                    return
                if item.seq <= high:
                    continue
                high = item.seq
                yield item.encode()
        finally:
            if queue in self._subscribers:
                self._subscribers.remove(queue)

    # -- RunObserver --------------------------------------------------------

    async def message_started(self, *, run_id: UUID, message_id: UUID) -> None:
        """Records that the assistant message started."""
        self.message_id = message_id
        await self.emit("message.started", {"message_id": str(message_id)})

    async def token(self, *, run_id: UUID, delta: str) -> None:
        """Records one streamed token."""
        await self.emit("llm.token", {"delta": delta})

    async def reasoning(self, *, run_id: UUID, delta: str) -> None:
        """Records one streamed chunk of the model's thinking."""
        await self.emit("llm.reasoning", {"delta": delta})

    async def tool_started(self, *, run_id: UUID, call: ToolCall) -> None:
        """Records that a tool call started."""
        await self.emit(
            "tool.started",
            {
                "tool": call.tool,
                "args_hash": call.args_hash,
                "args_json": call.args_json,
            },
        )

    async def tool_finished(self, *, run_id: UUID, call: ToolCall) -> None:
        """Records that a tool call finished."""
        await self.emit(
            "tool.finished",
            {
                "tool": call.tool,
                "args_hash": call.args_hash,
                "status": call.status,
                "duration_ms": call.duration_ms,
                "error_code": call.error_code,
                "args_json": call.args_json,
                "result_preview": call.result_preview,
            },
        )

    async def resource_read(self, *, run_id: UUID, access: ResourceAccess) -> None:
        """Records that a resource was read."""
        await self.emit(
            "resource.read",
            {
                "uri": access.uri,
                "size_bytes": access.size_bytes,
                "mime_type": access.mime_type,
            },
        )

    async def approval_required(
        self,
        *,
        run_id: UUID,
        approval: ApprovalRequest,
    ) -> None:
        """Records that the run waits for a human decision."""
        await self.emit(
            "approval.required",
            {
                "approval_id": str(approval.approval_id),
                "tool": approval.tool,
                "args_hash": approval.args_hash,
                "reason": approval.reason,
            },
        )

    async def approval_resolved(
        self,
        *,
        run_id: UUID,
        approval_id: UUID,
        approved: bool,
    ) -> None:
        """Records that a pending approval was decided."""
        await self.emit(
            "approval.resolved",
            {"approval_id": str(approval_id), "approved": approved},
        )

    async def message_completed(self, *, run: AgentRun) -> None:
        """Records the final trace of the assistant message."""
        await self.emit(
            "message.completed",
            {
                "status": run.status,
                "final_answer": run.final_answer,
                "reasoning": run.reasoning,
                "tools_called": [call.as_record().__dict__ for call in run.tool_calls],
                "resources_accessed": [access.__dict__ for access in run.resources_accessed],
                "token_usage": run.usage.__dict__,
                "approvals": [
                    {
                        "approval_id": str(request.approval_id),
                        "tool": request.tool,
                        "reason": request.reason,
                    }
                    for request in run.approvals
                ],
            },
        )
        # A pause ends this stream too: the decision arrives on a new one. Without
        # the terminal frame a client that waits for `done` (or for the response
        # to close) would hang, and the approval card would never settle.
        await self.emit("done", {"status": run.status})

    async def failed(self, *, run_id: UUID, error: str) -> None:
        """Records a failure and closes the stream."""
        await self.emit("error", {"message": error})
