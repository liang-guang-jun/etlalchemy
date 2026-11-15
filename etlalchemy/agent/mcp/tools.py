"""Turns MCP tools into LangChain tools with policy, limits and tracing.

One adapter owns everything that must happen around a tool call:

* the approval decision of :class:`~etlalchemy.agent.security.policy.ApprovalPolicy`,
  including the LangGraph ``interrupt`` that pauses the run for a human answer;
* the per-call timeout and the output truncation that protects the context
  window;
* the structured ``[not_found]`` / ``[conflict]`` / ``[internal]`` categories the
  model uses to correct itself;
* the events the streamer forwards to the caller.
"""

from __future__ import annotations

import inspect
import json
import time
from asyncio import Lock
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from hashlib import sha256
from typing import Any, Literal

from langchain_core.tools import BaseTool, StructuredTool
from langgraph.errors import GraphBubbleUp
from langgraph.types import interrupt
from mcp.types import CallToolResult, Tool
from pydantic import BaseModel, Field, create_model

from etlalchemy.agent.errors import parse_tool_error
from etlalchemy.agent.redaction import preview_json, preview_text, redact_arguments
from etlalchemy.agent.results import ApprovalRequest, RunObserver, ToolCall
from etlalchemy.agent.security.policy import ApprovalPolicy
from etlalchemy.agent.settings import AgentRuntimeSettings
from etlalchemy.conversation.aggregates.types import ResourceAccess
from etlalchemy.shared.logging import get_logger

TRUNCATION_MARKER = "…(truncated)"
"""Suffix appended to an over-long tool result."""

ApprovalFn = Callable[[dict[str, Any]], Any]
"""Pauses the graph until a human answers; ``langgraph.types.interrupt`` by default."""

_JSON_TO_PY: dict[str, Any] = {
    "string": str,
    "integer": int,
    "number": float,
    "boolean": bool,
    "array": list[Any],
    "object": dict[str, Any],
}


@dataclass(frozen=True)
class ToolAnnotations:
    """The MCP hints that drive the approval policy."""

    read_only: bool = False
    """Whether the tool is annotated as read-only."""
    destructive: bool = False
    """Whether the tool is annotated as destructive."""
    has_hints: bool = True
    """Whether the tool carries any annotation at all."""


def annotations_of(tool: Tool) -> ToolAnnotations:
    """Reads the snake_case MCP hints of one tool."""
    annotations = tool.annotations
    return ToolAnnotations(
        read_only=bool(getattr(annotations, "read_only_hint", False)),
        destructive=bool(getattr(annotations, "destructive_hint", False)),
        has_hints=annotations is not None,
    )


def args_hash(arguments: Mapping[str, Any]) -> str:
    """Returns a stable digest of a tool argument mapping."""
    encoded = json.dumps(arguments, sort_keys=True, default=str, ensure_ascii=False)
    return sha256(encoded.encode("utf-8")).hexdigest()[:32]


def _field_for(spec: Mapping[str, Any], *, required: bool) -> tuple[Any, Any]:
    """Builds one annotated field of a generated argument model.

    ``enum`` becomes a ``Literal`` so pydantic rejects an out-of-range value, and
    an explicit ``default`` is honoured for optional arguments.
    """
    kind = spec.get("type")
    if isinstance(kind, list):
        kind = next((item for item in kind if item != "null"), None)
    choices = spec.get("enum")
    annotation: Any = _JSON_TO_PY.get(str(kind or ""), Any)
    if isinstance(choices, list) and choices:
        annotation = Literal[tuple(choices)]
    description = str(spec.get("description") or "")
    if required:
        return annotation, Field(..., description=description)
    if "default" in spec:
        return annotation, Field(default=spec["default"], description=description)
    optional = annotation if annotation is Any else annotation | None
    return optional, Field(default=None, description=description)


def build_args_model(tool_name: str, schema: Mapping[str, Any]) -> type[BaseModel]:
    """Builds a pydantic model from an MCP ``inputSchema``.

    Only the JSON Schema subset the server emits is covered: scalar types, arrays
    and objects. Anything else is exposed as ``Any`` so the model still sees the
    tool.

    Args:
        tool_name: Name of the tool, used to name the generated model.
        schema: The ``inputSchema`` advertised by the MCP server.

    Returns:
        A pydantic model class describing the tool arguments.
    """
    properties = schema.get("properties") or {}
    required = set(schema.get("required") or [])
    fields: dict[str, Any] = {
        str(name): _field_for(spec or {}, required=str(name) in required)
        for name, spec in properties.items()
    }
    model_name = f"{tool_name.title().replace('_', '')}Args"
    return create_model(model_name, **fields)


def result_text(result: CallToolResult) -> str:
    """Returns the textual payload of a tool result."""
    parts: list[str] = []
    for block in result.content or []:
        text = getattr(block, "text", None)
        if isinstance(text, str):
            parts.append(text)
    if parts:
        return "\n".join(parts)
    structured = getattr(result, "structuredContent", None)
    if structured:
        return json.dumps(structured, ensure_ascii=False, default=str)
    return ""


def truncate(text: str, limit: int) -> str:
    """Truncates a tool result to the configured character budget."""
    if limit <= 0 or len(text) <= limit:
        return text
    return text[: max(0, limit - len(TRUNCATION_MARKER))] + TRUNCATION_MARKER


def _reason(exc: Exception) -> str:
    """Returns a non-empty one-line reason for a failed call."""
    return str(exc).strip() or type(exc).__name__


class ToolExecutor:
    """Runs MCP tool calls behind the policy, the limits and the observer."""

    def __init__(
        self,
        call_tool: Callable[..., Awaitable[CallToolResult]],
        policy: ApprovalPolicy,
        settings: AgentRuntimeSettings,
        observer: RunObserver | None = None,
        approval: ApprovalFn | None = None,
        run_id: Any = None,
        auto_approve: bool = False,
        approval_ids: Callable[[str, str], Any] | None = None,
        approval_decided: Callable[[Any, Any, bool], Awaitable[None]] | None = None,
    ) -> None:
        """Stores the transport, the policy, the limits and the run identity."""
        self._call_tool = call_tool
        self._policy = policy
        self._settings = settings
        self._observer = observer
        self._approval = approval or interrupt
        self._run_id = run_id
        self._auto_approve = auto_approve
        self._new_approval_id = approval_ids
        self._approval_decided = approval_decided
        self._approval_turn = Lock()
        self._paused = False
        self._log = get_logger("agent.tools")

    async def call(
        self,
        name: str,
        arguments: Mapping[str, Any],
        *,
        annotations: ToolAnnotations,
        context: Mapping[str, str] | None = None,
    ) -> str:
        """Calls one tool and returns the text the model should read.

        Args:
            name: Tool name.
            arguments: Parsed tool arguments.
            annotations: MCP hints of the tool.
            context: Values approval rules may require.

        Returns:
            The tool output, truncated to the configured budget, or the refusal
            text when the policy denies the call.
        """
        payload = {key: value for key, value in arguments.items() if value is not None}
        digest = args_hash(payload)
        policy = self._policy.decide(
            name,
            read_only=annotations.read_only,
            destructive=annotations.destructive,
            has_hints=annotations.has_hints,
            context=dict(context or {}),
        )
        # Auto-approve answers the question the policy would ask, so it also lifts
        # the ``deny`` that only exists because no rule matched the tool. A rule
        # that declares ``deny`` states a deployment decision and keeps refusing.
        if policy.decision == "deny" and not (self._auto_approve and policy.defaulted):
            return f"[denied] {name} requires an approval that the policy refuses"
        if (
            policy.decision == "require_approval"
            and not self._auto_approve
            and not await self._approve(name, digest, policy.reason)
        ):
            return f"[denied] the user rejected the call to {name}"
        if policy.decision != "auto" and self._auto_approve:
            # The reader turned the human gate off; the call runs as if it had been
            # approved, and no card is created for it.
            self._log.info(
                "agent.tool.approval.skipped",
                tool=name,
                run_id=str(self._run_id),
                policy=policy.decision,
            )
        return await self._execute(name, payload, digest)

    async def _approve(self, name: str, digest: str, reason: str) -> bool:
        """Pauses the run and returns whether the human approved the call.

        Approvals are asked **one at a time, in call order**. LangGraph matches the
        resume values of a task to its ``interrupt`` calls by position, so the
        asks must happen in a stable order; ``ToolNode`` starts the calls of a
        turn concurrently, hence the lock.

        A paused step is thrown away, so only the **first** ask of one execution
        reaches the human: once an ``interrupt`` paused this step, the remaining
        calls stop here and are asked, in the same order, on the next resume. They
        are therefore neither refused on the user's behalf nor asked twice, and
        exactly one approval is pending at every pause.
        """
        async with self._approval_turn:
            if self._paused:
                # The value is discarded with the rest of the paused step; the call
                # runs again, and asks for itself, when the run is resumed.
                return False
            approval_id = (
                self._new_approval_id(name, digest) if self._new_approval_id is not None else None
            )
            payload = {
                "approval_id": str(approval_id) if approval_id is not None else None,
                "run_id": str(self._run_id) if self._run_id is not None else None,
                "tool": name,
                "args_hash": digest,
                "reason": reason,
            }
            if self._observer is not None and approval_id is not None:
                await self._observer.approval_required(
                    run_id=self._run_id,
                    approval=ApprovalRequest(
                        approval_id=approval_id,
                        run_id=self._run_id,
                        tool=name,
                        args_hash=digest,
                        reason=reason,
                    ),
                )
            try:
                answer = self._approval(payload)
                if inspect.isawaitable(answer):
                    answer = await answer
            except GraphBubbleUp:
                self._paused = True
                raise
            approved = bool(answer.get("approved")) if isinstance(answer, Mapping) else bool(answer)
            if approval_id is not None and self._approval_decided is not None:
                # Reaching this line means the graph resumed instead of pausing:
                # LangGraph re-runs the tool and answers the fresh interrupt with
                # the decision of the first one, so the approval would otherwise
                # stay ``pending`` on a run that already moved on.
                await self._approval_decided(self._run_id, approval_id, approved)
            return approved

    async def _execute(self, name: str, payload: Mapping[str, Any], digest: str) -> str:
        """Calls the tool, traces it and returns its truncated text.

        A failure is returned as text instead of being raised. The graph aborts
        on an exception, but only the model can recover: it retries with better
        arguments, picks another tool or explains the failure to the reader. The
        run budgets and the approval interrupt still propagate, because those
        end the run on purpose.
        """
        started = time.perf_counter()
        args_json = self._arguments_preview(payload)
        call = ToolCall(tool=name, args_hash=digest, status="running", args_json=args_json)
        if self._observer is not None:
            await self._observer.tool_started(run_id=self._run_id, call=call)
        try:
            result = await self._call_tool(
                name,
                payload,
                timeout_seconds=self._settings.limits.tool_timeout_seconds,
            )
        except TimeoutError:
            timeout = self._settings.limits.tool_timeout_seconds
            detail = f"tool {name} timed out after {timeout}s"
            return await self._failed(
                name,
                digest,
                args_json,
                started,
                "timeout",
                "[timeout]",
                detail,
            )
        except GraphBubbleUp:
            raise
        except Exception as exc:
            detail = f"tool {name} failed: {_reason(exc)}"
            return await self._failed(
                name,
                digest,
                args_json,
                started,
                "error",
                "[internal]",
                detail,
            )
        text = result_text(result)
        code: str | None = None
        status = "ok"
        if result.is_error:
            code = parse_tool_error(text)[0]
            status = "error"
        call = ToolCall(
            tool=name,
            args_hash=digest,
            status=status,
            duration_ms=_elapsed_ms(started),
            error_code=code,
            args_json=args_json,
            result_preview=preview_text(
                text,
                self._settings.limits.max_tool_result_preview_chars,
            ),
        )
        await self._notify_finished(call)
        return truncate(text, self._settings.limits.max_tool_output_chars)

    def _arguments_preview(self, payload: Mapping[str, Any]) -> str:
        """Returns the redacted, truncated arguments shown in the browser."""
        redacted = redact_arguments(payload, self._settings.redact_argument_keys)
        return preview_json(redacted, self._settings.limits.max_tool_args_chars)

    async def _failed(
        self,
        name: str,
        digest: str,
        args_json: str,
        started: float,
        status: str,
        code: str,
        detail: str,
    ) -> str:
        """Traces a failed call and returns the text the model should read."""
        text = truncate(f"{code} {detail}", self._settings.limits.max_tool_output_chars)
        self._log.warning("agent.tool.failed", tool=name, run_id=str(self._run_id), error=detail)
        await self._notify_finished(
            ToolCall(
                tool=name,
                args_hash=digest,
                status=status,
                duration_ms=_elapsed_ms(started),
                error_code=code,
                args_json=args_json,
                result_preview=preview_text(
                    text,
                    self._settings.limits.max_tool_result_preview_chars,
                ),
            )
        )
        return text

    async def _notify_finished(self, call: ToolCall) -> None:
        """Forwards the finished call to the observer, if any."""
        if self._observer is None:
            return
        await self._observer.tool_finished(run_id=self._run_id, call=call)
        self._log.debug(
            "agent.tool.call",
            tool=call.tool,
            status=call.status,
            duration_ms=call.duration_ms,
            run_id=str(self._run_id),
        )


def _elapsed_ms(started: float) -> int:
    """Returns the milliseconds elapsed since ``started``."""
    return int((time.perf_counter() - started) * 1000)


def to_langchain_tool(
    tool: Tool,
    executor: ToolExecutor,
    *,
    context: Mapping[str, str] | None = None,
) -> BaseTool:
    """Wraps one MCP tool as a LangChain ``StructuredTool``.

    Args:
        tool: Tool advertised by the MCP server.
        executor: Executor that applies the policy, the limits and the tracing.
        context: Values approval rules may require.

    Returns:
        A tool the model can call; the description is copied verbatim.
    """
    annotations = annotations_of(tool)
    model = build_args_model(tool.name, tool.input_schema or {})

    async def invoke(**kwargs: Any) -> str:
        return await executor.call(
            tool.name,
            kwargs,
            annotations=annotations,
            context=context,
        )

    return StructuredTool.from_function(
        coroutine=invoke,
        name=tool.name,
        description=tool.description or tool.name,
        args_schema=model,
    )


def tool_resource_access(uri: str, size_bytes: int, mime_type: str) -> ResourceAccess:
    """Builds the trace record of one resource read."""
    return ResourceAccess(uri=uri, size_bytes=size_bytes, mime_type=mime_type)
