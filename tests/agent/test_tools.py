"""Tests of the MCP tool adapter."""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest
from etlalchemy.agent.errors import parse_tool_error
from etlalchemy.agent.mcp.tools import (
    ToolAnnotations,
    ToolExecutor,
    args_hash,
    build_args_model,
    to_langchain_tool,
    truncate,
)
from etlalchemy.agent.results import AgentRun, ApprovalRequest, ToolCall
from etlalchemy.agent.security.policy import ApprovalPolicy
from etlalchemy.agent.settings import AgentLimits, AgentRuntimeSettings, ApprovalRule
from pydantic import ValidationError

from tests.agent.support import FakeMcpClient


class RecordingObserver:
    """Observer that records the tool events of one run."""

    def __init__(self) -> None:
        """Starts with no event."""
        self.started: list[str] = []
        self.finished: list[ToolCall] = []
        self.approvals: list[ApprovalRequest] = []

    async def tool_started(self, *, run_id: UUID, call: ToolCall) -> None:
        """Records a tool start."""
        self.started.append(call.tool)

    async def tool_finished(self, *, run_id: UUID, call: ToolCall) -> None:
        """Records a tool end."""
        self.finished.append(call)

    async def approval_required(self, *, run_id: UUID, approval: ApprovalRequest) -> None:
        """Records a pending approval."""
        self.approvals.append(approval)

    async def message_started(self, *, run_id: UUID, message_id: UUID) -> None:  # pragma: no cover
        """Ignores the message start."""

    async def token(self, *, run_id: UUID, delta: str) -> None:  # pragma: no cover
        """Ignores tokens."""

    async def resource_read(self, *, run_id: UUID, access: Any) -> None:  # pragma: no cover
        """Ignores resource reads."""

    async def approval_resolved(
        self,
        *,
        run_id: UUID,
        approval_id: UUID,
        approved: bool,
    ) -> None:  # pragma: no cover
        """Ignores decisions."""

    async def message_completed(self, *, run: AgentRun) -> None:  # pragma: no cover
        """Ignores completions."""

    async def failed(self, *, run_id: UUID, error: str) -> None:  # pragma: no cover
        """Ignores failures."""


def executor(
    client: FakeMcpClient,
    *,
    observer: RecordingObserver | None = None,
    approval: Any = None,
    limits: AgentLimits | None = None,
) -> ToolExecutor:
    """Builds an executor over the fake client."""
    settings = AgentRuntimeSettings(limits=limits or AgentLimits())
    return ToolExecutor(
        client.call_tool,
        ApprovalPolicy(settings),
        settings,
        observer=observer,
        approval=approval,
        run_id=uuid4(),
        approval_ids=lambda tool, digest: uuid4(),
    )


def test_args_hash_is_stable_and_order_insensitive() -> None:
    """The digest ignores mapping order and is reproducible."""
    assert args_hash({"a": 1, "b": 2}) == args_hash({"b": 2, "a": 1})
    assert args_hash({"a": 1}) != args_hash({"a": 2})


def test_truncate_marks_the_cut() -> None:
    """An over-long text is cut and marked."""
    assert truncate("abcdef", 0) == "abcdef"
    assert truncate("abcdef", 10) == "abcdef"
    cut = truncate("x" * 100, 20)
    assert len(cut) == 20
    assert cut.endswith("…(truncated)")


def test_args_model_marks_optional_fields() -> None:
    """Required properties become required, the rest default to ``None``."""
    model = build_args_model(
        "list_models",
        {
            "type": "object",
            "properties": {
                "catalog": {"type": "string", "description": "catalog id"},
                "limit": {"type": "integer"},
            },
            "required": ["catalog"],
        },
    )
    parsed = model(catalog="c")
    assert parsed.catalog == "c"
    assert parsed.limit is None


def test_args_model_supports_enum_and_default() -> None:
    """An ``enum`` becomes a validated literal and a ``default`` is honoured."""
    model = build_args_model(
        "pick",
        {
            "type": "object",
            "properties": {
                "mode": {"type": "string", "enum": ["fast", "slow"], "default": "fast"},
                "limit": {"type": "integer", "default": 10},
            },
        },
    )

    defaults = model()
    assert defaults.mode == "fast"
    assert defaults.limit == 10
    assert model(mode="slow").mode == "slow"
    with pytest.raises(ValidationError):
        model(mode="nope")


def test_parse_tool_error_splits_the_category() -> None:
    """The bracketed prefix becomes the category."""
    assert parse_tool_error("[not_found] missing") == ("[not_found]", "missing")
    assert parse_tool_error("plain failure") == ("[internal]", "plain failure")


async def test_read_only_call_skips_approval() -> None:
    """A read-only tool runs and is traced."""
    client = FakeMcpClient()
    observer = RecordingObserver()
    tool_executor = executor(client, observer=observer)
    text = await tool_executor.call(
        "list_models",
        {"catalog": "c"},
        annotations=ToolAnnotations(read_only=True),
    )
    assert text == "ok"
    assert client.calls[0].name == "list_models"
    assert client.calls[0].arguments == {"catalog": "c"}
    assert observer.started == ["list_models"]
    assert observer.finished[0].status == "ok"


async def test_the_browser_sees_redacted_arguments_and_the_result() -> None:
    """The call carries the argument preview and the result, never a secret."""
    client = FakeMcpClient()
    client.result_text = "42 rows"
    observer = RecordingObserver()
    tool_executor = executor(client, observer=observer)
    await tool_executor.call(
        "create_connection",
        {"name": "crm", "options": {"token": "s3cret"}, "timeout": 5},
        annotations=ToolAnnotations(read_only=True),
    )
    finished = observer.finished[0]
    assert "s3cret" not in finished.args_json
    assert '"name": "crm"' in finished.args_json
    assert '"timeout": 5' in finished.args_json
    assert finished.result_preview == "42 rows"


async def test_a_resumed_approval_records_its_decision() -> None:
    """A tool re-run by a resume closes the approval it opened.

    LangGraph re-executes the paused tool and answers the fresh interrupt with
    the decision of the first one, so the approval must not stay pending.
    """
    client = FakeMcpClient()
    decisions: list[tuple[Any, bool]] = []

    async def decided(run_id: Any, approval_id: Any, approved: bool) -> None:
        decisions.append((approval_id, approved))

    settings = AgentRuntimeSettings(
        approval_rules=(ApprovalRule(match="approve_*", action="require_approval"),),
    )
    tool_executor = ToolExecutor(
        client.call_tool,
        ApprovalPolicy(settings),
        settings,
        approval=lambda payload: {"approved": True},
        run_id=uuid4(),
        approval_ids=lambda tool, digest: uuid4(),
        approval_decided=decided,
    )

    text = await tool_executor.call(
        "approve_term",
        {},
        annotations=ToolAnnotations(destructive=True),
    )

    assert text == "ok"
    assert [approved for _, approved in decisions] == [True]
    assert client.calls[0].name == "approve_term"


async def test_the_argument_preview_honours_its_limit() -> None:
    """A long argument value is truncated before it reaches the browser."""
    client = FakeMcpClient()
    observer = RecordingObserver()
    tool_executor = executor(
        client,
        observer=observer,
        limits=AgentLimits(max_tool_args_chars=20),
    )
    await tool_executor.call(
        "search_fields",
        {"term": "x" * 200},
        annotations=ToolAnnotations(read_only=True),
    )
    assert len(observer.finished[0].args_json) == 20


async def test_destructive_call_is_denied_by_default() -> None:
    """Without an approval the tool never reaches the server."""
    client = FakeMcpClient()
    tool_executor = executor(client)
    text = await tool_executor.call(
        "discard_catalog",
        {},
        annotations=ToolAnnotations(destructive=True),
    )
    assert text.startswith("[denied]")
    assert client.calls == []


async def test_approval_is_requested_and_honoured() -> None:
    """A matching rule pauses the call until the human approves it."""
    client = FakeMcpClient()
    observer = RecordingObserver()
    settings = AgentRuntimeSettings(
        approval_rules=(ApprovalRule(match="discard_*", action="require_approval"),),
    )
    tool_executor = ToolExecutor(
        client.call_tool,
        ApprovalPolicy(settings),
        settings,
        observer=observer,
        approval=lambda payload: {"approved": True},
        run_id=uuid4(),
        approval_ids=lambda tool, digest: uuid4(),
    )
    text = await tool_executor.call(
        "discard_catalog",
        {},
        annotations=ToolAnnotations(destructive=True),
    )
    assert text == "ok"
    assert client.calls[0].name == "discard_catalog"
    assert len(observer.approvals) == 1
    assert observer.approvals[0].tool == "discard_catalog"


async def test_rejected_approval_stops_the_call() -> None:
    """A denied decision never reaches the server."""
    client = FakeMcpClient()
    settings = AgentRuntimeSettings(
        approval_rules=(ApprovalRule(match="discard_*", action="require_approval"),),
    )
    tool_executor = ToolExecutor(
        client.call_tool,
        ApprovalPolicy(settings),
        settings,
        approval=lambda payload: {"approved": False},
        run_id=uuid4(),
        approval_ids=lambda tool, digest: uuid4(),
    )
    text = await tool_executor.call(
        "discard_catalog",
        {},
        annotations=ToolAnnotations(destructive=True),
    )
    assert text.startswith("[denied]")
    assert client.calls == []


async def test_auto_approve_skips_the_question() -> None:
    """With the switch on, a destructive call runs without asking anybody."""
    client = FakeMcpClient()
    observer = RecordingObserver()
    asked: list[dict[str, Any]] = []

    async def approval(payload: dict[str, Any]) -> dict[str, Any]:
        asked.append(payload)
        return {"approved": False}

    settings = AgentRuntimeSettings(
        approval_rules=(ApprovalRule(match="discard_*", action="require_approval"),),
    )
    tool_executor = ToolExecutor(
        client.call_tool,
        ApprovalPolicy(settings),
        settings,
        observer=observer,
        approval=approval,
        run_id=uuid4(),
        auto_approve=True,
        approval_ids=lambda tool, digest: uuid4(),
    )

    text = await tool_executor.call(
        "discard_catalog",
        {},
        annotations=ToolAnnotations(destructive=True),
    )

    assert text == "ok"
    assert asked == []
    assert observer.approvals == []
    assert client.calls[0].name == "discard_catalog"


async def test_auto_approve_lifts_the_default_deny() -> None:
    """A destructive tool no rule mentions still runs with the switch on.

    The configured default is ``deny``, so without this the reader who turned
    auto-approve on would see ``[denied] ... requires an approval that the policy
    refuses`` for every tool outside the rule list.
    """
    client = FakeMcpClient()
    observer = RecordingObserver()
    settings = AgentRuntimeSettings(
        approval_default="deny",
        approval_rules=(ApprovalRule(match="discard_*", action="require_approval"),),
    )
    tool_executor = ToolExecutor(
        client.call_tool,
        ApprovalPolicy(settings),
        settings,
        observer=observer,
        run_id=uuid4(),
        auto_approve=True,
        approval_ids=lambda tool, digest: uuid4(),
    )

    text = await tool_executor.call(
        "remove_diagram",
        {},
        annotations=ToolAnnotations(destructive=True),
    )

    assert text == "ok"
    assert observer.approvals == []
    assert client.calls[0].name == "remove_diagram"


async def test_auto_approve_keeps_a_refusing_rule() -> None:
    """A rule that declares ``deny`` outranks the switch."""
    client = FakeMcpClient()
    settings = AgentRuntimeSettings(
        approval_rules=(ApprovalRule(match="discard_*", action="deny"),),
    )
    tool_executor = ToolExecutor(
        client.call_tool,
        ApprovalPolicy(settings),
        settings,
        run_id=uuid4(),
        auto_approve=True,
        approval_ids=lambda tool, digest: uuid4(),
    )

    text = await tool_executor.call(
        "discard_catalog",
        {},
        annotations=ToolAnnotations(destructive=True),
    )

    assert text.startswith("[denied]")
    assert client.calls == []


async def test_error_output_keeps_its_category() -> None:
    """An errored result is traced with its bracketed category."""
    client = FakeMcpClient()
    client.result_text = "[not_found] table 1 does not exist"
    client.is_error = True
    observer = RecordingObserver()
    tool_executor = executor(client, observer=observer)
    text = await tool_executor.call(
        "get_table",
        {},
        annotations=ToolAnnotations(read_only=True),
    )
    assert text.startswith("[not_found]")
    assert observer.finished[0].status == "error"
    assert observer.finished[0].error_code == "[not_found]"


async def test_timeout_is_reported() -> None:
    """A slow tool answers with a timeout text instead of aborting the run."""

    async def slow(*args: Any, **kwargs: Any) -> Any:
        raise TimeoutError

    observer = RecordingObserver()
    settings = AgentRuntimeSettings(limits=AgentLimits(tool_timeout_seconds=1))
    tool_executor = ToolExecutor(
        slow,
        ApprovalPolicy(settings),
        settings,
        observer=observer,
        run_id=uuid4(),
        approval_ids=lambda tool, digest: uuid4(),
    )

    text = await tool_executor.call(
        "list_models",
        {},
        annotations=ToolAnnotations(read_only=True),
    )

    assert text.startswith("[timeout] tool list_models timed out")
    assert observer.finished[0].status == "timeout"
    assert observer.finished[0].error_code == "[timeout]"


async def test_a_broken_call_is_returned_to_the_model() -> None:
    """A transport failure becomes a tool result the model can explain."""

    async def broken(*args: Any, **kwargs: Any) -> Any:
        msg = "cannot connect to the MCP endpoint 'in-process'"
        raise ConnectionError(msg)

    observer = RecordingObserver()
    settings = AgentRuntimeSettings(limits=AgentLimits())
    tool_executor = ToolExecutor(
        broken,
        ApprovalPolicy(settings),
        settings,
        observer=observer,
        run_id=uuid4(),
        approval_ids=lambda tool, digest: uuid4(),
    )

    text = await tool_executor.call(
        "list_models",
        {},
        annotations=ToolAnnotations(read_only=True),
    )

    assert text.startswith("[internal] tool list_models failed: cannot connect")
    assert observer.finished[0].status == "error"
    assert observer.finished[0].error_code == "[internal]"


async def test_langchain_tool_copies_name_and_description() -> None:
    """The exposed tool keeps the MCP name and description verbatim."""
    client = FakeMcpClient()
    tool = _fake_tool("list_models", "List the models of a catalog.")
    wrapped = to_langchain_tool(tool, executor(client))
    assert wrapped.name == "list_models"
    assert wrapped.description == "List the models of a catalog."
    result = await wrapped.ainvoke({"catalog": "c"})
    assert result == "ok"
    assert client.calls[0].arguments == {"catalog": "c"}


def _fake_tool(name: str, description: str) -> Any:
    """Builds the subset of an MCP tool the adapter reads."""

    class _Annotations:
        read_only_hint = True
        destructive_hint = False

    class _Tool:
        def __init__(self) -> None:
            self.name = name
            self.description = description
            self.input_schema = {
                "type": "object",
                "properties": {"catalog": {"type": "string"}},
            }
            self.annotations = _Annotations()

    return _Tool()
