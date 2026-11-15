"""Tests of the SSE streamer."""

from __future__ import annotations

from uuid import uuid4

from etlalchemy.agent.results import AgentRun, ApprovalRequest, ToolCall
from etlalchemy.agent.service.streaming import RunStream
from etlalchemy.conversation.aggregates.types import ResourceAccess


async def collect(stream: RunStream, after_seq: int = 0) -> list[str]:
    """Drains the stream until it closes."""
    frames: list[str] = []
    async for frame in stream.events(after_seq, heartbeat_seconds=0.01):
        frames.append(frame)
    return frames


async def test_events_are_numbered_and_encoded() -> None:
    """Every event gets a monotonic sequence number and an SSE frame."""
    run_id = uuid4()
    stream = RunStream(run_id)
    first = await stream.emit("message.started", {"message_id": str(uuid4())})
    second = await stream.emit("llm.token", {"delta": "hi"})

    assert (first.seq, second.seq) == (1, 2)
    frame = second.encode()
    assert frame.startswith("id: 2\nevent: llm.token\ndata: ")
    assert '"delta": "hi"' in frame
    assert str(run_id) in frame


async def test_replay_returns_the_missing_events() -> None:
    """A reconnect with ``Last-Event-ID`` continues after that number."""
    stream = RunStream(uuid4())
    for index in range(3):
        await stream.emit("llm.token", {"delta": str(index)})

    assert [event.seq for event in stream.replay(0)] == [1, 2, 3]
    assert [event.seq for event in stream.replay(2)] == [3]


async def test_stream_stops_on_done() -> None:
    """The terminal event closes the stream and unblocks the reader."""
    stream = RunStream(uuid4())
    await stream.emit("message.started", {})
    await stream.emit("done", {})
    frames = await collect(stream)
    kinds = [line for frame in frames for line in frame.splitlines() if line.startswith("event:")]
    assert kinds == ["event: message.started", "event: done"]
    assert stream.closed is True


async def test_heartbeat_is_sent_while_idle() -> None:
    """An idle stream emits comment frames instead of closing."""
    stream = RunStream(uuid4())
    frames: list[str] = []
    generator = stream.events(heartbeat_seconds=0.01)
    frames.append(await anext(generator))
    await stream.emit("done", {})
    async for frame in generator:
        frames.append(frame)
    assert frames[0] == ": ping\n\n"


async def test_observer_methods_emit_the_documented_events() -> None:
    """The observer surface maps onto the documented event names."""
    stream = RunStream(uuid4())
    run_id = stream.run_id
    message_id = uuid4()
    await stream.message_started(run_id=run_id, message_id=message_id)
    await stream.reasoning(run_id=run_id, delta="thinking")
    await stream.token(run_id=run_id, delta="hi")
    await stream.tool_started(
        run_id=run_id,
        call=ToolCall(tool="t", args_hash="h", args_json='{"a": 1}'),
    )
    await stream.tool_finished(
        run_id=run_id,
        call=ToolCall(
            tool="t",
            args_hash="h",
            status="ok",
            duration_ms=3,
            args_json='{"a": 1}',
            result_preview="ok",
        ),
    )
    await stream.resource_read(
        run_id=run_id,
        access=ResourceAccess(uri="catalog:///all", size_bytes=4),
    )
    await stream.approval_required(
        run_id=run_id,
        approval=ApprovalRequest(
            approval_id=uuid4(),
            run_id=run_id,
            tool="discard_catalog",
            args_hash="h",
            reason="destructive",
        ),
    )
    await stream.message_completed(
        run=AgentRun(
            run_id=run_id,
            conversation_id=uuid4(),
            message_id=message_id,
            status="completed",
            final_answer="done",
            reasoning="thinking",
            tool_calls=[ToolCall(tool="t", args_hash="h", result_preview="ok")],
        ),
    )
    kinds = [event.kind for event in stream.replay(0)]
    assert kinds == [
        "message.started",
        "llm.reasoning",
        "llm.token",
        "tool.started",
        "tool.finished",
        "resource.read",
        "approval.required",
        "message.completed",
        "done",
    ]
    finished = next(event for event in stream.replay(0) if event.kind == "tool.finished")
    assert finished.data["args_json"] == '{"a": 1}'
    assert finished.data["result_preview"] == "ok"
    completed = next(event for event in stream.replay(0) if event.kind == "message.completed")
    assert completed.data["reasoning"] == "thinking"
    assert completed.data["tools_called"][0]["result_preview"] == "ok"


async def test_a_paused_run_ends_the_stream() -> None:
    """A pause closes the stream, so the client stops waiting for more events."""
    stream = RunStream(uuid4())
    run_id = stream.run_id
    await stream.message_started(run_id=run_id, message_id=uuid4())
    await stream.message_completed(
        run=AgentRun(
            run_id=run_id,
            conversation_id=uuid4(),
            message_id=uuid4(),
            status="awaiting_approval",
        ),
    )

    kinds = [(event.kind, event.data.get("status")) for event in stream.replay(0)]
    assert kinds[-2:] == [
        ("message.completed", "awaiting_approval"),
        ("done", "awaiting_approval"),
    ]
    assert stream.closed is True


async def test_metrics_report_the_buffer_pressure() -> None:
    """The metrics expose how many events the replay buffer had to evict."""
    stream = RunStream(uuid4(), buffer_size=2)
    for index in range(3):
        await stream.emit("llm.token", {"delta": str(index)})

    metrics = stream.metrics()

    assert metrics["events"] == 3
    assert metrics["buffered"] == 2
    assert metrics["dropped"] == 1
    assert metrics["closed"] is False


async def test_failure_closes_the_stream() -> None:
    """A failure emits ``error`` and closes the stream."""
    stream = RunStream(uuid4())
    await stream.failed(run_id=stream.run_id, error="boom")
    assert stream.closed is True
    assert stream.replay(0)[-1].kind == "error"


async def test_event_emitted_while_replaying_is_not_lost() -> None:
    """An event produced between two replayed frames still reaches the reader."""
    stream = RunStream(uuid4())
    await stream.emit("message.started", {})
    generator = stream.events(heartbeat_seconds=0.01)
    first = await anext(generator)
    # The generator is suspended inside the replay loop; the emitter wins the
    # race before the (old) implementation had subscribed.
    await stream.emit("llm.token", {"delta": "late"})
    second = await anext(generator)
    await stream.emit("done", {})
    rest = [frame async for frame in generator]

    assert "event: message.started" in first
    assert "event: llm.token" in second
    assert any("event: done" in frame for frame in rest)


async def test_each_event_is_delivered_once() -> None:
    """Replayed and live frames never duplicate an event."""
    stream = RunStream(uuid4())
    await stream.emit("llm.token", {"delta": "a"})
    generator = stream.events(heartbeat_seconds=0.01)
    frames = [await anext(generator)]
    await stream.emit("llm.token", {"delta": "b"})
    frames.append(await anext(generator))
    await stream.emit("done", {})
    frames.extend([frame async for frame in generator])

    deltas = [frame for frame in frames if '"delta"' in frame]
    assert sum('"a"' in frame for frame in deltas) == 1
    assert sum('"b"' in frame for frame in deltas) == 1
