"""Tests of the answer a run records for its own turn."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langgraph.checkpoint.memory import MemorySaver

from etlalchemy.agent.runtime import NO_ANSWER_TEXT, AgentRunner, RunRequest, _final_text
from etlalchemy.agent.settings import AgentLimits, AgentRuntimeSettings
from tests.agent.support import FakeConversation, FakeMcpClient

GREETING = "Hello! I'm doing great, thank you. How can I assist you today?"


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


def _runner(conversation: FakeConversation, model: _ScriptedModel) -> AgentRunner:
    """Builds a runner over the fake conversation and the scripted model."""

    async def chat_model_factory(*_: object) -> object:
        return model

    return AgentRunner(
        client=FakeMcpClient(),  # type: ignore[arg-type]
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
        content="build a sales model",
    )


def test_final_text_ignores_the_replayed_history() -> None:
    """An empty current turn must not answer with the previous turn's text."""
    values = {
        "messages": [
            HumanMessage(content="hi"),
            AIMessage(content=GREETING),
            HumanMessage(content="build a sales model"),
            AIMessage(content=""),
        ],
    }

    assert _final_text(values, turn="build a sales model") == ""


def test_final_text_reads_the_current_turn() -> None:
    """The answer of the current turn is what the run records."""
    values = {
        "messages": [
            HumanMessage(content="hi"),
            AIMessage(content=GREETING),
            HumanMessage(content="build a sales model"),
            AIMessage(content="created the schema"),
        ],
    }

    assert _final_text(values, turn="build a sales model") == "created the schema"


async def test_an_empty_turn_does_not_repeat_the_greeting() -> None:
    """A model that answers nothing is not replaced by a replayed message."""
    conversation = FakeConversation()
    conversation.messages.extend(
        [
            {"role": "user", "content": "hi", "id": uuid4()},
            {"role": "assistant", "content": GREETING, "id": uuid4()},
        ],
    )
    model = _ScriptedModel(script=[AIMessage(content="")])
    runner = _runner(conversation, model)

    run = await runner.run(_request())

    assert run.status == "completed"
    assert run.final_answer == NO_ANSWER_TEXT
    assert conversation.messages[-1]["content"] == NO_ANSWER_TEXT


async def test_an_empty_turn_is_nudged_once() -> None:
    """The model is asked to continue, so a silent stop still ends in an answer."""
    conversation = FakeConversation()
    model = _ScriptedModel(
        script=[AIMessage(content=""), AIMessage(content="created the schema")],
    )
    runner = _runner(conversation, model)

    run = await runner.run(_request())

    assert run.final_answer == "created the schema"
    assert conversation.messages[-1]["content"] == "created the schema"
    # The nudge reached the model as one more turn.
    assert len(model.seen) == 2
    assert model.seen[-1][-1].content == (
        "Your previous message was empty. Continue the task, or answer the user now "
        "in the language they write in."
    )
