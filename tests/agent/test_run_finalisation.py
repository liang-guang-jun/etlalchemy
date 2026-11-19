"""Tests of the run finalisation paths that used to leave a run ``running``."""

from __future__ import annotations

import asyncio
from typing import Any
from uuid import uuid4

import pytest
from etlalchemy.agent.runtime import AgentRunner, RunRequest
from etlalchemy.agent.settings import AgentLimits, AgentRuntimeSettings
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage
from langchain_core.outputs import ChatResult
from langgraph.checkpoint.memory import MemorySaver

from tests.agent.support import FakeConversation, FakeMcpClient


class _HangingModel(BaseChatModel):
    """Fake model that never answers, so a running task can be cancelled."""

    @property
    def _llm_type(self) -> str:
        """Returns the provider name of the fake."""
        return "hanging-fake"

    async def _agenerate(
        self,
        messages: list[BaseMessage],
        stop: Any = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        """Waits forever; only the cancellation ends the call."""
        await asyncio.Event().wait()
        msg = "unreachable"
        raise AssertionError(msg)

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: Any = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        """Rejects the synchronous path, which the runtime never uses."""
        msg = "the runtime streams, so it only calls the async path"
        raise AssertionError(msg)

    def bind_tools(self, tools: object, **kwargs: object) -> _HangingModel:
        """Returns the model itself, so the graph can bind tools."""
        return self


def _runner(conversation: FakeConversation, factory: Any) -> AgentRunner:
    """Builds a runner around the given model factory."""
    return AgentRunner(
        client=FakeMcpClient(),  # type: ignore[arg-type]
        settings=AgentRuntimeSettings(limits=AgentLimits(max_tool_calls=3)),
        conversation=conversation,
        chat_model_factory=factory,  # type: ignore[arg-type]
        checkpointer=MemorySaver(),
    )


def _request() -> RunRequest:
    """Builds a run request for a fresh conversation."""
    return RunRequest(
        conversation_id=uuid4(),
        session_id=uuid4(),
        user_id=uuid4(),
        tenant_id=None,
        content="list the models",
    )


async def test_a_cancelled_run_does_not_stay_running() -> None:
    """A dropped client cancels the task; the run must still leave `running`."""
    conversation = FakeConversation()

    async def chat_model_factory(*_: object) -> object:
        return _HangingModel()

    runner = _runner(conversation, chat_model_factory)
    task = asyncio.create_task(runner.run(_request()))
    for _ in range(200):
        if conversation.runs:
            break
        await asyncio.sleep(0.01)

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert conversation.runs[-1]["status"] == "interrupted"
    # The partial answer is kept, so the chat still shows what was streamed.
    assert conversation.messages[-1]["role"] == "assistant"
    assert conversation.messages[-1]["interrupted"] is True


async def test_a_model_that_cannot_be_built_closes_the_run() -> None:
    """A provider or credential failure happens before the graph, and still counts."""
    conversation = FakeConversation()

    async def chat_model_factory(*_: object) -> object:
        msg = "provider is not configured"
        raise RuntimeError(msg)

    runner = _runner(conversation, chat_model_factory)

    with pytest.raises(RuntimeError):
        await runner.run(_request())

    assert conversation.runs[-1]["status"] == "failed"
    assert conversation.runs[-1]["error"] == "provider is not configured"
