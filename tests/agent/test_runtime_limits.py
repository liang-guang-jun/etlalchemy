"""Tests of the runtime limits: token budget, history window and approvals."""

from __future__ import annotations

import asyncio
from typing import Any
from uuid import uuid4

from etlalchemy.agent.mcp.tools import ToolAnnotations, ToolExecutor
from etlalchemy.agent.runtime import AgentRunner, RunRequest
from etlalchemy.agent.security.policy import ApprovalPolicy
from etlalchemy.agent.settings import AgentLimits, AgentRuntimeSettings, ApprovalRule
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from tests.agent.support import (
    FakeConversation,
    FakeMcpClient,
    FakeObserver,
    RecordingModel,
    UsageChatModel,
)


def request(**overrides: object) -> RunRequest:
    """Builds a run request."""
    parameters: dict[str, object] = {
        "conversation_id": uuid4(),
        "session_id": uuid4(),
        "user_id": uuid4(),
        "tenant_id": None,
        "content": "and then?",
    }
    parameters.update(overrides)
    return RunRequest(**parameters)  # type: ignore[arg-type]


def runner_with(
    model: Any,
    conversation: FakeConversation,
    settings: AgentRuntimeSettings,
) -> AgentRunner:
    """Builds a runner around the given model, conversation and settings."""

    async def chat_model_factory(*_: object) -> object:
        return model

    return AgentRunner(
        client=FakeMcpClient(),  # type: ignore[arg-type]
        settings=settings,
        conversation=conversation,
        chat_model_factory=chat_model_factory,  # type: ignore[arg-type]
        checkpointer=None,
    )


async def test_token_budget_stops_the_run() -> None:
    """Usage above ``token_budget`` fails the run instead of continuing."""
    expensive = UsageChatModel(
        message=AIMessage(
            content="expensive answer",
            usage_metadata={"input_tokens": 80, "output_tokens": 40, "total_tokens": 120},
        ),
    )
    conversation = FakeConversation()
    runner = runner_with(
        expensive,
        conversation,
        AgentRuntimeSettings(limits=AgentLimits(token_budget=10)),
    )

    run = await runner.run(request(), observer=FakeObserver())

    assert run.status == "failed"
    assert run.error is not None
    assert "token budget" in run.error
    assert conversation.messages[-1]["interrupted"] is True


async def test_usage_below_the_budget_finishes_normally() -> None:
    """The budget only rejects a run that really exceeds it."""
    cheap = UsageChatModel(
        message=AIMessage(
            content="cheap answer",
            usage_metadata={"input_tokens": 1, "output_tokens": 1, "total_tokens": 2},
        ),
    )
    runner = runner_with(
        cheap,
        FakeConversation(),
        AgentRuntimeSettings(limits=AgentLimits(token_budget=1000)),
    )

    run = await runner.run(request())

    assert run.status == "completed"
    assert run.usage.total_tokens == 2


async def test_history_is_replayed_up_to_the_limit() -> None:
    """Without a checkpointer the last ``history_limit`` messages are replayed."""
    conversation = FakeConversation()
    for index in range(4):
        conversation.messages.append(
            {
                "role": "user" if index % 2 == 0 else "assistant",
                "content": f"m{index}",
                "id": uuid4(),
            },
        )
    model = RecordingModel(messages=iter([AIMessage(content="done")]))
    runner = runner_with(
        model,
        conversation,
        AgentRuntimeSettings(limits=AgentLimits(max_tool_calls=3), history_limit=2),
    )

    await runner.run(request(content="current"))

    first_call = model.seen[0]
    contents = [message.content for message in first_call]
    assert contents[-1] == "current"
    assert "m2" in contents
    assert "m3" in contents
    assert "m0" not in contents
    assert isinstance(first_call[-1], HumanMessage)


async def test_history_is_replayed_when_the_run_has_its_own_thread() -> None:
    """A checkpointer holds only its run, so the store supplies the context."""
    from langgraph.checkpoint.memory import MemorySaver

    conversation = FakeConversation()
    conversation.messages.append({"role": "user", "content": "old", "id": uuid4()})
    model = RecordingModel(messages=iter([AIMessage(content="done")]))

    async def chat_model_factory(*_: object) -> object:
        return model

    runner = AgentRunner(
        client=FakeMcpClient(),  # type: ignore[arg-type]
        settings=AgentRuntimeSettings(history_limit=2),
        conversation=conversation,
        chat_model_factory=chat_model_factory,  # type: ignore[arg-type]
        checkpointer=MemorySaver(),
    )

    await runner.run(request(content="current"))

    contents = [
        message.content for message in model.seen[0] if not isinstance(message, SystemMessage)
    ]
    assert contents == ["old", "current"]


async def test_blank_history_rows_are_not_replayed() -> None:
    """An interrupted answer with no text is dropped instead of sent empty."""
    conversation = FakeConversation()
    conversation.messages.append({"role": "user", "content": "old", "id": uuid4()})
    conversation.messages.append({"role": "assistant", "content": "  ", "id": uuid4()})
    model = RecordingModel(messages=iter([AIMessage(content="done")]))
    runner = runner_with(
        model,
        conversation,
        AgentRuntimeSettings(history_limit=4),
    )

    await runner.run(request(content="current"))

    contents = [
        message.content for message in model.seen[0] if not isinstance(message, SystemMessage)
    ]
    assert contents == ["old", "current"]


async def test_page_context_is_spliced_into_the_system_prompt() -> None:
    """The page the reader shows travels as instructions, not as the message."""
    conversation = FakeConversation()
    model = RecordingModel(messages=iter([AIMessage(content="done")]))
    runner = runner_with(model, conversation, AgentRuntimeSettings())

    await runner.run(
        request(
            content="which of these can I delete?",
            page_context="Business terms › domain 1108 › term Metrics\nPath: /vocabulary/1108",
        ),
    )

    system = next(message for message in model.seen[0] if isinstance(message, SystemMessage))
    assert "Business terms › domain 1108 › term Metrics" in system.content
    assert isinstance(model.seen[0][-1], HumanMessage)
    assert model.seen[0][-1].content == "which of these can I delete?"
    assert conversation.messages[0]["content"] == "which of these can I delete?"


async def test_no_page_context_leaves_the_system_prompt_alone() -> None:
    """Without a page the prompt carries no placement section."""
    conversation = FakeConversation()
    model = RecordingModel(messages=iter([AIMessage(content="done")]))
    runner = runner_with(model, conversation, AgentRuntimeSettings())

    await runner.run(request(content="hello"))

    system = next(message for message in model.seen[0] if isinstance(message, SystemMessage))
    assert "has this page open" not in system.content


async def test_two_destructive_calls_ask_one_after_another() -> None:
    """The second approval waits its turn instead of being refused."""
    settings = AgentRuntimeSettings(
        approval_rules=(ApprovalRule(match="discard_*", action="require_approval"),),
    )
    started = asyncio.Event()
    release = asyncio.Event()
    approvals: list[str] = []

    async def approval(payload: dict[str, Any]) -> dict[str, Any]:
        approvals.append(str(payload["tool"]))
        if len(approvals) == 1:
            started.set()
            await release.wait()
        return {"approved": True}

    client = FakeMcpClient()
    executor = ToolExecutor(
        client.call_tool,
        ApprovalPolicy(settings),
        settings,
        approval=approval,
        run_id=uuid4(),
        approval_ids=lambda tool, digest: uuid4(),
    )

    first = asyncio.create_task(
        executor.call("discard_one", {}, annotations=ToolAnnotations(destructive=True)),
    )
    await asyncio.wait_for(started.wait(), timeout=2.0)
    second = asyncio.create_task(
        executor.call("discard_two", {}, annotations=ToolAnnotations(destructive=True)),
    )
    # The second call is queued behind the pending one, not answered for the user.
    await asyncio.sleep(0.05)
    assert approvals == ["discard_one"]
    release.set()
    results = await asyncio.wait_for(asyncio.gather(first, second), timeout=2.0)

    assert list(results) == ["ok", "ok"]
    assert approvals == ["discard_one", "discard_two"]
    assert [call.name for call in client.calls] == ["discard_one", "discard_two"]
