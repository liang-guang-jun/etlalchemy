"""Fakes shared by the agent tests."""

from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID, uuid4

from etlalchemy.agent.results import AgentRun, ApprovalRequest, ToolCall
from etlalchemy.conversation.aggregates.errors import ApprovalAlreadyDecidedError
from etlalchemy.conversation.aggregates.types import ResourceAccess, TokenUsage
from etlalchemy.conversation.application import MessageRef, RunRef
from langchain_core.language_models import BaseChatModel
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult


class RecordingModel(GenericFakeChatModel):
    """Fake chat model that records the messages it is asked to answer."""

    seen: list[list[BaseMessage]] = []

    def bind_tools(self, tools: object, **kwargs: object) -> RecordingModel:
        """Returns the model itself, so the graph can bind tools."""
        return self

    async def ainvoke(self, input: Any, config: Any = None, **kwargs: Any) -> Any:
        """Records the input and answers with the next scripted message."""
        messages = input if isinstance(input, list) else input.get("messages", [])
        self.seen.append(list(messages))
        return await super().ainvoke(input, config, **kwargs)



class UsageChatModel(BaseChatModel):
    """Chat model that answers once and reports its token usage.

    ``GenericFakeChatModel`` drops ``usage_metadata`` while streaming, so the
    budget tests need a model that keeps it on the ``on_chat_model_end`` event.
    """

    message: AIMessage
    calls: int = 0

    @property
    def _llm_type(self) -> str:
        """Returns the provider name of the fake."""
        return "usage-fake"

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: Any = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        """Answers with the fixed message."""
        self.calls += 1
        return ChatResult(generations=[ChatGeneration(message=self.message)])

    def bind_tools(self, tools: object, **kwargs: object) -> UsageChatModel:
        """Returns the model itself, so the graph can bind tools."""
        return self


@dataclass
class RecordedCall:
    """One tool call a fake MCP client received."""

    name: str
    arguments: dict[str, Any]


class FakeMcpClient:
    """Stand-in for :class:`etlalchemy.agent.mcp.client.McpClient`."""

    def __init__(self) -> None:
        """Starts with no tools, resources or prompts."""
        self.calls: list[RecordedCall] = []
        self.result_text: str = "ok"
        self.is_error: bool = False
        self.tool_lists = 0
        self.resource_lists = 0
        self.prompt_lists = 0
        self.lifespans = 0

    @asynccontextmanager
    async def lifespan(self) -> Any:
        """Counts how often the runner asked for a shared session."""
        self.lifespans += 1
        yield self

    async def list_tools(self) -> list[Any]:
        """Returns no tools by default."""
        self.tool_lists += 1
        return []

    async def list_resources(self) -> list[Any]:
        """Returns no static resources."""
        self.resource_lists += 1
        return []

    async def list_resource_templates(self) -> list[Any]:
        """Returns no resource templates."""
        return []

    async def list_prompts(self) -> list[Any]:
        """Returns no prompts."""
        self.prompt_lists += 1
        return []

    async def read_resource(self, uri: str) -> Any:
        """Answers a resource read with a JSON payload."""
        return _ReadResult(text='{"ok": true}', mime_type="application/json")

    async def get_prompt(self, name: str, arguments: Any = None) -> Any:
        """Renders a fixed prompt."""
        return _PromptResult(text=f"prompt {name}")

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any],
        *,
        timeout_seconds: float | None = None,
    ) -> Any:
        """Records the call and answers with the configured result."""
        self.calls.append(RecordedCall(name=name, arguments=dict(arguments)))
        return _CallResult(text=self.result_text, is_error=self.is_error)


@dataclass
class _ReadResult:
    """Minimal read-resource result."""

    text: str
    mime_type: str

    @property
    def contents(self) -> list[Any]:
        """Returns one textual content block."""
        return [_Content(text=self.text, mimeType=self.mime_type)]


@dataclass
class _Content:
    """Minimal content block."""

    text: str
    mimeType: str


@dataclass
class _PromptResult:
    """Minimal prompt result."""

    text: str

    @property
    def messages(self) -> list[Any]:
        """Returns one message holding the rendered text."""
        return [_Message(text=self.text)]


@dataclass
class _Message:
    """Minimal prompt message."""

    text: str

    @property
    def content(self) -> Any:
        """Returns the content block of the message."""
        return _Content(text=self.text, mimeType="text/plain")


@dataclass
class _CallResult:
    """Minimal call-tool result."""

    text: str
    is_error: bool = False

    @property
    def content(self) -> list[Any]:
        """Returns one textual content block."""
        return [_Content(text=self.text, mimeType="text/plain")]

    @property
    def structuredContent(self) -> None:
        """Returns no structured payload."""
        return None


class FakeObserver:
    """Records the events a runner emits."""

    def __init__(self) -> None:
        """Starts with no event."""
        self.events: list[tuple[str, dict[str, Any]]] = []

    async def message_started(self, *, run_id: UUID, message_id: UUID) -> None:
        """Records the start of a message."""
        self.events.append(("message.started", {"run_id": run_id, "message_id": message_id}))

    async def token(self, *, run_id: UUID, delta: str) -> None:
        """Records one token."""
        self.events.append(("llm.token", {"delta": delta}))

    async def tool_started(self, *, run_id: UUID, call: ToolCall) -> None:
        """Records a tool start."""
        self.events.append(("tool.started", {"tool": call.tool}))

    async def tool_finished(self, *, run_id: UUID, call: ToolCall) -> None:
        """Records a tool end."""
        self.events.append(("tool.finished", {"tool": call.tool, "status": call.status}))

    async def resource_read(self, *, run_id: UUID, access: ResourceAccess) -> None:
        """Records a resource read."""
        self.events.append(("resource.read", {"uri": access.uri}))

    async def approval_required(self, *, run_id: UUID, approval: ApprovalRequest) -> None:
        """Records a pending approval."""
        self.events.append(("approval.required", {"tool": approval.tool}))

    async def approval_resolved(
        self,
        *,
        run_id: UUID,
        approval_id: UUID,
        approved: bool,
    ) -> None:
        """Records a decision."""
        self.events.append(("approval.resolved", {"approved": approved}))

    async def message_completed(self, *, run: AgentRun) -> None:
        """Records the completed message."""
        self.events.append(("message.completed", {"status": run.status}))

    async def failed(self, *, run_id: UUID, error: str) -> None:
        """Records a failure."""
        self.events.append(("error", {"message": error}))


@dataclass
class FakeConversation:
    """Stand-in for the conversation application the runner writes to."""

    session_id: UUID = field(default_factory=uuid4)
    messages: list[dict[str, Any]] = field(default_factory=list)
    runs: list[dict[str, Any]] = field(default_factory=list)
    approvals: list[dict[str, Any]] = field(default_factory=list)
    decisions: list[dict[str, Any]] = field(default_factory=list)

    async def append_user_message(
        self,
        session_id: UUID,
        conversation_id: UUID,
        content: str,
        message_id: UUID | None = None,
    ) -> MessageRef:
        """Records a user message."""
        resolved = message_id or uuid4()
        self.messages.append({"role": "user", "content": content, "id": resolved})
        return MessageRef(message_id=resolved, conversation_id=conversation_id)

    async def complete_assistant_message(
        self,
        session_id: UUID,
        conversation_id: UUID,
        content: str,
        message_id: UUID | None = None,
        resources: tuple[ResourceAccess, ...] = (),
        tools: tuple[Any, ...] = (),
        token_usage: TokenUsage | None = None,
        interrupted: bool = False,
        reasoning: str = "",
    ) -> MessageRef:
        """Records an assistant message with its trace."""
        resolved = message_id or uuid4()
        self.messages.append(
            {
                "role": "assistant",
                "content": content,
                "id": resolved,
                "resources": list(resources),
                "tools": list(tools),
                "usage": token_usage,
                "interrupted": interrupted,
                "reasoning": reasoning,
            },
        )
        return MessageRef(message_id=resolved, conversation_id=conversation_id)

    async def start_run(
        self,
        session_id: UUID,
        conversation_id: UUID,
        message_id: UUID,
        run_id: UUID | None = None,
    ) -> RunRef:
        """Records a run."""
        resolved = run_id or uuid4()
        self.runs.append({"run_id": resolved, "message_id": message_id})
        return RunRef(run_id=resolved, conversation_id=conversation_id)

    async def request_approval(
        self,
        session_id: UUID,
        conversation_id: UUID,
        run_id: UUID,
        tool: str,
        args_hash: str,
        reason: str,
        approval_id: UUID | None = None,
    ) -> UUID:
        """Records a pending approval."""
        resolved = approval_id or uuid4()
        if any(item["approval_id"] == resolved for item in self.approvals):
            msg = f"approval {resolved} already exists on run {run_id}"
            raise ApprovalAlreadyDecidedError(msg)
        self.approvals.append(
            {"approval_id": resolved, "run_id": run_id, "tool": tool, "reason": reason},
        )
        return resolved

    async def decide_approval(
        self,
        session_id: UUID,
        conversation_id: UUID,
        run_id: UUID,
        approval_id: UUID,
        approved: bool,
    ) -> None:
        """Records a decision."""
        if any(
            item["approval_id"] == approval_id
            for item in self.decisions
            if isinstance(item, dict)
        ):
            msg = f"approval {approval_id} is already decided"
            raise ApprovalAlreadyDecidedError(msg)
        self.decisions.append({"approval_id": approval_id, "approved": approved})

    async def finish_run(
        self,
        session_id: UUID,
        conversation_id: UUID,
        run_id: UUID,
        status: str,
        error: str | None = None,
    ) -> None:
        """Records the terminal status of a run."""
        self.runs.append({"run_id": run_id, "status": status, "error": error})

    async def list_messages(
        self,
        session_id: UUID,
        conversation_id: UUID,
        limit: int | None = None,
        offset: int = 0,
        newest_first: bool = False,
    ) -> list[Any]:
        """Returns the recorded messages, honouring the requested window."""
        window = list(reversed(self.messages)) if newest_first else list(self.messages)
        window = window[offset:]
        if limit is not None:
            window = window[:limit]
        return [_row(message) for message in window]


def _row(message: dict[str, Any]) -> Any:
    """Builds a read-model-looking row from a recorded message."""

    class _Row:
        pass

    row = _Row()
    row.message_id = message["id"]
    row.conversation_id = uuid4()
    row.role = message["role"]
    row.content = message["content"]
    row.interrupted = message.get("interrupted", False)
    row.input_tokens = 0
    row.output_tokens = 0
    return row
