"""Tests of how the runner reacts to a failing tool call."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from etlalchemy.agent.runtime import AgentRunner, RunRequest
from etlalchemy.agent.settings import AgentLimits, AgentRuntimeSettings
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langgraph.checkpoint.memory import MemorySaver

from tests.agent.support import FakeConversation, FakeMcpClient


class _FailingReadClient(FakeMcpClient):
    """Fake client whose first resource read fails like a wrong URI does."""

    def __init__(self) -> None:
        """Starts with no read."""
        super().__init__()
        self.reads = 0

    async def read_resource(self, uri: str) -> Any:
        """Fails the first read, then answers like the base fake."""
        self.reads += 1
        if self.reads == 1:
            msg = f"Resource not found: {uri!r}"
            raise RuntimeError(msg)
        return await super().read_resource(uri)


class _ScriptedModel(BaseChatModel):
    """Fake model that answers the scripted messages in order."""

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
        """Records the input and answers with the next scripted message."""
        self.seen.append(list(messages))
        message = self.script[min(self.index, len(self.script) - 1)]
        self.index += 1
        return ChatResult(generations=[ChatGeneration(message=message)])

    def bind_tools(self, tools: object, **kwargs: object) -> _ScriptedModel:
        """Returns the model itself, so the graph can bind tools."""
        return self


def _runner(
    conversation: FakeConversation,
    client: FakeMcpClient,
    model: _ScriptedModel,
) -> AgentRunner:
    """Builds a runner over the fake client and the scripted model."""

    async def chat_model_factory(*_: object) -> object:
        return model

    return AgentRunner(
        client=client,  # type: ignore[arg-type]
        settings=AgentRuntimeSettings(limits=AgentLimits(max_tool_calls=10)),
        conversation=conversation,
        chat_model_factory=chat_model_factory,  # type: ignore[arg-type]
        checkpointer=MemorySaver(),
    )


def _request() -> RunRequest:
    """Builds a run request for a fresh conversation."""
    return RunRequest(
        conversation_id=uuid4(),
        session_id=uuid4(),
        user_id=uuid4(),
        tenant_id=None,
        content="what schemas does the catalog have?",
    )


async def test_a_failed_tool_call_does_not_end_the_run() -> None:
    """The model reads the failure and answers instead of the graph aborting."""
    conversation = FakeConversation()
    client = _FailingReadClient()
    model = _ScriptedModel(
        script=[
            AIMessage(
                content="reading the catalog",
                tool_calls=[
                    {
                        "name": "read_mcp_resource",
                        "args": {"uri": "catalog:///nope/schemas"},
                        "id": "call-1",
                    },
                ],
            ),
            AIMessage(content="the resource does not exist, so I cannot list it"),
        ],
    )
    runner = _runner(conversation, client, model)

    run = await runner.run(_request())

    assert run.status == "completed"
    assert run.final_answer == "the resource does not exist, so I cannot list it"
    assert client.reads == 1
    # The second turn carried the failure, so the model could react to it.
    assert "[internal] cannot read resource" in str(model.seen[-1])
    tools = conversation.messages[-1]["tools"]
    assert [(call.tool, call.error_code) for call in tools] == [
        ("read_mcp_resource", "[internal]"),
    ]
