"""Tests of the LangGraph runner with a fake model and a fake MCP client."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from etlalchemy.agent.runtime import AgentRunner, RunRequest
from etlalchemy.agent.settings import AgentLimits, AgentRuntimeSettings, ApprovalRule
from langchain_core.language_models import BaseChatModel
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langgraph.checkpoint.memory import MemorySaver

from tests.agent.support import FakeConversation, FakeMcpClient, FakeObserver


class _FakeModel(GenericFakeChatModel):
    """Fake chat model that accepts tool binding without using it."""

    def bind_tools(self, tools: object, **kwargs: object) -> _FakeModel:
        """Returns the model itself, so the graph can bind tools."""
        return self


def make_runner(
    conversation: FakeConversation,
    *,
    settings: AgentRuntimeSettings | None = None,
) -> AgentRunner:
    """Builds a runner whose model answers with one fixed message."""
    model = _FakeModel(messages=iter([AIMessage(content="all done")]))

    async def chat_model_factory(provider_id: object, user_id: object, tenant_id: object) -> object:
        return model

    client = FakeMcpClient()
    return AgentRunner(
        client=client,  # type: ignore[arg-type]
        settings=settings or AgentRuntimeSettings(limits=AgentLimits(max_tool_calls=3)),
        conversation=conversation,
        chat_model_factory=chat_model_factory,  # type: ignore[arg-type]
        checkpointer=MemorySaver(),
    )


def make_request(**overrides: object) -> RunRequest:
    """Builds a run request for a fresh conversation."""
    parameters: dict[str, object] = {
        "conversation_id": uuid4(),
        "session_id": uuid4(),
        "user_id": uuid4(),
        "tenant_id": None,
        "content": "list the models",
    }
    parameters.update(overrides)
    return RunRequest(**parameters)  # type: ignore[arg-type]


async def test_run_records_the_conversation_and_the_result() -> None:
    """A completed run writes both messages, the run and its final answer."""
    conversation = FakeConversation()
    runner = make_runner(conversation)
    observer = FakeObserver()

    run = await runner.run(make_request(), observer=observer)

    assert run.status == "completed"
    assert run.final_answer == "all done"
    assert [message["role"] for message in conversation.messages] == ["user", "assistant"]
    assert conversation.messages[1]["content"] == "all done"
    assert conversation.runs[0]["run_id"] == run.run_id
    assert conversation.runs[-1]["status"] == "completed"
    kinds = [kind for kind, _ in observer.events]
    assert kinds[0] == "message.started"
    assert kinds[-1] == "message.completed"


async def test_awaiting_approval_keeps_a_resumable_run() -> None:
    """A run paused on an approval is not finalised in the conversation."""
    conversation = FakeConversation()
    runner = make_runner(conversation)

    run = await runner.run(make_request())

    assert run.status == "completed"
    assert conversation.approvals == []


def _destructive_tool(name: str) -> Any:
    """Builds the subset of an MCP tool the adapter reads."""

    class _Annotations:
        read_only_hint = False
        destructive_hint = True

    class _Tool:
        def __init__(self) -> None:
            self.name = name
            self.description = f"{name} something"
            self.input_schema = {"type": "object", "properties": {}}
            self.annotations = _Annotations()

    return _Tool()


class _TwoToolClient(FakeMcpClient):
    """Fake client that advertises two destructive tools."""

    async def list_tools(self) -> list[Any]:
        """Returns the two tools the scripted model asks for."""
        return [_destructive_tool("discard_one"), _destructive_tool("discard_two")]


class _ScriptedModel(BaseChatModel):
    """Fake model that answers the scripted messages in order.

    ``GenericFakeChatModel`` streams its content, which drops ``tool_calls``; this
    one answers in a single generation so the tool calls reach the tool node.
    """

    script: list[AIMessage]
    index: int = 0
    seen: list[list[BaseMessage]] = []

    @property
    def _llm_type(self) -> str:
        """Returns the provider name of the fake."""
        return "scripted-fake"

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: Any = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        """Answers with the next scripted message."""
        self.seen.append(list(messages))
        message = self.script[min(self.index, len(self.script) - 1)]
        self.index += 1
        return ChatResult(generations=[ChatGeneration(message=message)])

    def bind_tools(self, tools: object, **kwargs: object) -> _ScriptedModel:
        """Returns the model itself, so the graph can bind tools."""
        return self


def _two_call_runner(conversation: FakeConversation, client: FakeMcpClient) -> AgentRunner:
    """Builds a runner whose model asks for both destructive tools in one turn."""
    model = _ScriptedModel(
        script=[
            AIMessage(
                content="calling both",
                tool_calls=[
                    {"name": "discard_one", "args": {}, "id": "call-1"},
                    {"name": "discard_two", "args": {}, "id": "call-2"},
                ],
            ),
            AIMessage(content="both done"),
        ],
    )

    async def chat_model_factory(*_: object) -> object:
        return model

    return AgentRunner(
        client=client,  # type: ignore[arg-type]
        settings=AgentRuntimeSettings(
            limits=AgentLimits(max_tool_calls=10),
            approval_rules=(ApprovalRule(match="discard_*", action="require_approval"),),
        ),
        conversation=conversation,
        chat_model_factory=chat_model_factory,  # type: ignore[arg-type]
        checkpointer=MemorySaver(),
    )


async def test_a_turn_asks_for_each_destructive_call_in_order() -> None:
    """Two destructive calls pause twice; neither is answered for the user."""
    conversation = FakeConversation()
    client = _TwoToolClient()
    runner = _two_call_runner(conversation, client)
    request = make_request()

    first = await runner.run(request)

    assert first.status == "awaiting_approval"
    assert [item["tool"] for item in conversation.approvals] == ["discard_one"]
    assert client.calls == []
    first_id = first.approvals[0].approval_id

    second = await runner.resume(
        request,
        run_id=first.run_id,
        message_id=first.message_id,
        approval_id=first_id,
        approved=True,
    )

    assert second.status == "awaiting_approval"
    assert [item["tool"] for item in conversation.approvals] == ["discard_one", "discard_two"]
    assert [item["approval_id"] for item in conversation.approvals][1] != first_id
    second_id = second.approvals[0].approval_id
    assert second_id != first_id

    final = await runner.resume(
        request,
        run_id=first.run_id,
        message_id=first.message_id,
        approval_id=second_id,
        approved=True,
    )

    assert final.status == "completed"
    assert final.final_answer == "both done"
    assert {call.name for call in client.calls} == {"discard_one", "discard_two"}
    # Nothing was refused on the user's behalf.
    assert [item["approved"] for item in conversation.decisions] == [True, True]


async def test_auto_approve_runs_destructive_calls_without_asking() -> None:
    """The switch of the panel skips the pause, so the turn finishes in one go."""
    conversation = FakeConversation()
    client = _TwoToolClient()
    runner = _two_call_runner(conversation, client)

    run = await runner.run(make_request(auto_approve=True))

    assert run.status == "completed"
    assert run.final_answer == "both done"
    assert conversation.approvals == []
    assert conversation.decisions == []
    assert {call.name for call in client.calls} == {"discard_one", "discard_two"}
