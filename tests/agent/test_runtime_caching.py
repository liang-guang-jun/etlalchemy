"""Tests of the runtime caches and of the terminal status mapping."""

from __future__ import annotations

import asyncio
from typing import Any
from uuid import uuid4

from etlalchemy.agent.runtime import AgentRunner, RunRequest
from etlalchemy.agent.settings import AgentLimits, AgentRuntimeSettings
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from tests.agent.support import FakeConversation, FakeMcpClient, RecordingModel


class SlowChatModel(BaseChatModel):
    """Chat model that takes longer than the run budget allows."""

    @property
    def _llm_type(self) -> str:
        """Returns the provider name of the fake."""
        return "slow-fake"

    async def _agenerate(
        self,
        messages: list[Any],
        stop: Any = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        """Sleeps before answering, so the wall clock expires first."""
        await asyncio.sleep(0.05)
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content="late"))])

    def _generate(
        self,
        messages: list[Any],
        stop: Any = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        """Blocks long enough to exceed the budget in a synchronous call."""
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content="late"))])

    def bind_tools(self, tools: object, **kwargs: object) -> SlowChatModel:
        """Returns the model itself, so the graph can bind tools."""
        return self


def request() -> RunRequest:
    """Builds a run request."""
    return RunRequest(
        conversation_id=uuid4(),
        session_id=uuid4(),
        user_id=uuid4(),
        tenant_id=None,
        content="hello",
    )


def runner_with(
    model: Any,
    conversation: FakeConversation,
    client: FakeMcpClient,
    settings: AgentRuntimeSettings | None = None,
) -> AgentRunner:
    """Builds a runner over the given doubles."""

    async def chat_model_factory(*_: object) -> object:
        return model

    return AgentRunner(
        client=client,  # type: ignore[arg-type]
        settings=settings or AgentRuntimeSettings(limits=AgentLimits()),
        conversation=conversation,
        chat_model_factory=chat_model_factory,  # type: ignore[arg-type]
        checkpointer=None,
    )


async def test_tool_definitions_are_fetched_once_per_runner() -> None:
    """Two runs reuse the tool list instead of re-listing MCP tools."""
    client = FakeMcpClient()
    runner = runner_with(
        RecordingModel(messages=iter([AIMessage(content="a"), AIMessage(content="b")])),
        FakeConversation(),
        client,
    )

    await runner.run(request())
    await runner.run(request())

    assert client.tool_lists == 1


async def test_the_catalogue_is_loaded_lazily_and_once() -> None:
    """The resources and prompts are fetched on the first run only."""
    client = FakeMcpClient()
    model = RecordingModel(messages=iter([AIMessage(content="a"), AIMessage(content="b")]))
    runner = runner_with(model, FakeConversation(), client)

    assert client.resource_lists == 0
    await runner.run(request())
    assert client.resource_lists == 1
    await runner.run(request())
    assert client.resource_lists == 1
    assert client.prompt_lists == 1


async def test_warm_up_preloads_the_catalogue() -> None:
    """Calling ``warm_up`` explicitly fetches the catalogue before any run."""
    client = FakeMcpClient()
    runner = runner_with(RecordingModel(messages=iter([AIMessage(content="a")])), FakeConversation(), client)

    await runner.warm_up()

    assert client.resource_lists == 1
    assert client.prompt_lists == 1


async def test_a_timed_out_run_is_persisted_as_interrupted() -> None:
    """The wall-clock budget marks the run ``interrupted``, not ``failed``."""
    conversation = FakeConversation()
    runner = runner_with(
        SlowChatModel(),
        conversation,
        FakeMcpClient(),
        AgentRuntimeSettings(limits=AgentLimits(max_wall_clock_seconds=0)),
    )

    run = await runner.run(request())

    assert run.status == "interrupted"
    assert conversation.runs[-1]["status"] == "interrupted"
    assert conversation.messages[-1]["interrupted"] is True


async def test_a_crashing_run_is_persisted_as_failed() -> None:
    """Any other failure stays ``failed``."""
    class BrokenModel(RecordingModel):
        async def ainvoke(self, input: Any, config: Any = None, **kwargs: Any) -> Any:
            raise RuntimeError("boom")

    conversation = FakeConversation()
    runner = runner_with(
        BrokenModel(messages=iter([AIMessage(content="never")])),
        conversation,
        FakeMcpClient(),
    )

    run = await runner.run(request())

    assert run.status == "failed"
    assert run.error is not None and "boom" in run.error
    assert conversation.runs[-1]["status"] == "failed"
