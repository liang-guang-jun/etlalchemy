"""Tests of the per-run recorder."""

from __future__ import annotations

from uuid import uuid4

import pytest

from etlalchemy.agent.errors import ToolBudgetExceededError
from etlalchemy.agent.results import ApprovalRequest, ToolCall
from etlalchemy.agent.runtime import RunRecorder, RunRequest, _approval_id, _approval_ids, _thread_id
from tests.agent.support import FakeConversation, FakeObserver


def make_recorder(max_tool_calls: int = 0) -> RunRecorder:
    """Builds a recorder with the given tool budget."""
    recorder = RunRecorder(
        FakeConversation(),
        RunRequest(
            conversation_id=uuid4(),
            session_id=uuid4(),
            user_id=uuid4(),
            tenant_id=None,
            content="hello",
        ),
        uuid4(),
        None,
    )
    recorder.max_tool_calls = max_tool_calls
    return recorder


async def test_tool_budget_counts_starts_not_finishes() -> None:
    """Two concurrent calls exceed a budget of one even before either finishes."""
    recorder = make_recorder(max_tool_calls=1)
    await recorder.tool_started(run_id=uuid4(), call=ToolCall(tool="first", args_hash="a"))
    with pytest.raises(ToolBudgetExceededError):
        await recorder.tool_started(run_id=uuid4(), call=ToolCall(tool="second", args_hash="b"))


async def test_tool_budget_allows_exactly_the_configured_calls() -> None:
    """A budget of two admits two starts and rejects the third."""
    recorder = make_recorder(max_tool_calls=2)
    for index in range(2):
        await recorder.tool_started(
            run_id=uuid4(),
            call=ToolCall(tool=f"t{index}", args_hash="h"),
        )
    with pytest.raises(ToolBudgetExceededError):
        await recorder.tool_started(run_id=uuid4(), call=ToolCall(tool="t3", args_hash="h"))


async def test_finished_calls_are_recorded_in_order() -> None:
    """The trace lists the calls in the order they finished."""
    recorder = make_recorder()
    first = ToolCall(tool="first", args_hash="a", status="ok")
    second = ToolCall(tool="second", args_hash="b", status="error")
    await recorder.tool_finished(run_id=uuid4(), call=first)
    await recorder.tool_finished(run_id=uuid4(), call=second)
    assert [call.tool for call in recorder.calls] == ["first", "second"]


async def test_reasoning_is_accumulated_and_capped() -> None:
    """The recorder keeps the thinking, never beyond its cap."""
    recorder = make_recorder()
    recorder.max_thinking_chars = 5
    await recorder.reasoning(run_id=uuid4(), delta="abc")
    await recorder.reasoning(run_id=uuid4(), delta="def")
    assert recorder.thinking == "abcde"


async def test_a_replayed_approval_is_not_forwarded_twice() -> None:
    """A resumed run re-executes the tool, so its ask must not reach the client."""
    conversation = FakeConversation()
    observer = FakeObserver()
    run_id = uuid4()
    recorder = RunRecorder(
        conversation,
        RunRequest(
            conversation_id=uuid4(),
            session_id=uuid4(),
            user_id=uuid4(),
            tenant_id=None,
            content="approve B",
        ),
        run_id,
        observer,
    )
    approval = ApprovalRequest(
        approval_id=uuid4(),
        run_id=run_id,
        tool="approve_term",
        args_hash="hash",
        reason="no hint",
    )

    await recorder.approval_required(run_id=run_id, approval=approval)
    await recorder.approval_required(run_id=run_id, approval=approval)

    assert [item["approval_id"] for item in conversation.approvals] == [approval.approval_id]
    kinds = [kind for kind, _ in observer.events]
    assert kinds.count("approval.required") == 1


async def test_a_replayed_decision_still_settles_the_card() -> None:
    """The route records the answer before the resume, but the card needs the event."""
    conversation = FakeConversation()
    observer = FakeObserver()
    run_id = uuid4()
    recorder = RunRecorder(
        conversation,
        RunRequest(
            conversation_id=uuid4(),
            session_id=uuid4(),
            user_id=uuid4(),
            tenant_id=None,
            content="approve B",
        ),
        run_id,
        observer,
    )
    approval_id = uuid4()

    await recorder.approval_decided(run_id, approval_id, True)
    await recorder.approval_decided(run_id, approval_id, True)

    # The write happens once; the event is forwarded every time, because a stream
    # that misses it renders the card as pending again on the next answer.
    assert len(conversation.decisions) == 1
    kinds = [kind for kind, _ in observer.events]
    assert kinds.count("approval.resolved") == 2


def test_an_approval_id_is_stable_per_call() -> None:
    """The same call of the same run always asks with the same id."""
    run_id = uuid4()
    first = _approval_id(run_id, "approve_term", "hash")
    assert first == _approval_id(run_id, "approve_term", "hash")
    assert first != _approval_id(run_id, "approve_term", "other")
    assert first != _approval_id(run_id, "create_term", "hash")
    assert first != _approval_id(uuid4(), "approve_term", "hash")


def test_identical_calls_of_one_run_get_distinct_ids() -> None:
    """Repeating the very same call in one turn is a second decision."""
    run_id = uuid4()
    factory = _approval_ids(run_id)

    first = factory("discard_term", "hash")
    second = factory("discard_term", "hash")

    assert first != second
    # A replay of the turn asks in the same order, so the ids repeat wholesale.
    assert first == _approval_id(run_id, "discard_term", "hash", 0)
    assert second == _approval_id(run_id, "discard_term", "hash", 1)


def test_every_run_owns_its_checkpoint_thread() -> None:
    """Two runs of one conversation never share a checkpoint thread."""
    conversation_id = uuid4()
    assert _thread_id(conversation_id, uuid4()) != _thread_id(conversation_id, uuid4())
