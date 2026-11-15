"""LangGraph orchestration of one agent run.

The runner owns the whole lifecycle of a message: it records the user message,
starts the run, streams the model and the tool events to an observer, and writes
the assistant message with its trace when the stream ends. A destructive tool
call interrupts the graph; the checkpoint keeps the run resumable, so an approval
may arrive minutes or days later, from another process.

Everything the runner touches outside this package is a port: the conversation
store, the chat model factory and the checkpoint saver are injected by the
assembly layer.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Annotated, Any, Protocol, TypedDict
from uuid import UUID, uuid4, uuid5

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode

from etlalchemy.agent.errors import TokenBudgetExceededError, ToolBudgetExceededError
from etlalchemy.agent.mcp.client import McpClient
from etlalchemy.agent.mcp.prompts import (
    RENDER_PROMPT_TOOL,
    build_prompt_catalogue,
    build_prompt_tool,
)
from etlalchemy.agent.mcp.resources import (
    READ_RESOURCE_TOOL,
    ResourceReader,
    build_catalogue,
    build_resource_tool,
)
from etlalchemy.agent.mcp.tools import ToolExecutor, args_hash, to_langchain_tool
from etlalchemy.agent.observability.mlflow import MlflowSettings, log_outcome, trace_run
from etlalchemy.agent.redaction import preview_json, preview_text, redact_arguments
from etlalchemy.agent.results import AgentRun, ApprovalRequest, RunObserver, ToolCall
from etlalchemy.agent.security.approval import ApprovalDecision, resume_command
from etlalchemy.agent.security.policy import ApprovalPolicy
from etlalchemy.agent.settings import AgentRuntimeSettings
from etlalchemy.conversation.aggregates.errors import ApprovalAlreadyDecidedError
from etlalchemy.conversation.aggregates.types import (
    ResourceAccess,
    RunStatus,
    TokenUsage,
    ToolCallRecord,
)
from etlalchemy.shared.logging import get_logger

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel
    from langchain_core.runnables import RunnableConfig
    from langchain_core.tools import BaseTool
    from langgraph.checkpoint.base import BaseCheckpointSaver

ChatModelFactory = Callable[[UUID | None, UUID, UUID | None], Awaitable["BaseChatModel"]]
"""``(provider_id, user_id, tenant_id) -> chat model``, injected by the assembly."""

REASONING_BLOCK_TYPES = frozenset({"reasoning", "reasoning_content", "thinking"})
"""Content-block types that carry thinking instead of the answer."""

APPROVAL_NAMESPACE = UUID("6f1d7d0e-2b39-4a55-9a3e-1d3c6f0a9b11")
"""Namespace of the deterministic approval ids of one run."""

PAGE_CONTEXT_CHARS = 2_000
"""Longest page context spliced into the system prompt."""

MAX_EMPTY_TURNS = 2
"""How often one run asks the model to continue after an empty answer."""

EMPTY_TURN_NUDGE = (
    "Your previous message was empty. Continue the task, or answer the user now "
    "in the language they write in."
)
"""Message sent back to the model when it ends a turn without saying anything."""

NO_ANSWER_TEXT = "(the model finished without an answer)"
"""Answer recorded when a completed run produced no assistant text at all."""


def _thread_id(conversation_id: UUID, run_id: UUID) -> str:
    """Returns the checkpoint thread of one run.

    Every run owns its thread, so a new message never inherits a half-finished
    graph state: an assistant message whose tool results were never written
    makes the provider answer 400 (``insufficient tool messages``). A resume
    reuses the thread of the run it continues, because the checkpoint is exactly
    what holds the pause.

    Args:
        conversation_id: Conversation the run belongs to.
        run_id: Run that owns the thread.

    Returns:
        The ``thread_id`` handed to LangGraph.
    """
    return f"{conversation_id!s}:{run_id!s}"


def _approval_id(run_id: UUID, tool: str, digest: str, occurrence: int = 0) -> UUID:
    """Returns the approval id of one tool call of a run.

    The id is derived from the call, not generated: a resumed run re-executes the
    paused tool, and a fresh id would register a second approval (and a second
    card) for a decision the human already made.

    Two *identical* calls in one turn would share tool and digest, so the
    occurrence of that pair in the run counts as well. Approvals are asked one at
    a time, so the counter advances in the same order on every replay.

    Args:
        run_id: Run that asks for the decision.
        tool: Name of the tool.
        digest: Digest of the arguments.
        occurrence: How many times that same call already asked in this run.

    Returns:
        The stable approval id.
    """
    return uuid5(APPROVAL_NAMESPACE, f"{run_id!s}:{tool}:{digest}:{occurrence}")


def _approval_ids(run_id: UUID) -> Callable[[str, str], UUID]:
    """Returns the approval id factory of one run.

    Args:
        run_id: Run that asks for the decisions.

    Returns:
        ``(tool, digest) -> approval id``, counting repeated identical calls.
    """
    seen: dict[tuple[str, str], int] = {}

    def next_id(tool: str, digest: str) -> UUID:
        """Returns the id of the next ask of this call."""
        occurrence = seen.get((tool, digest), 0)
        seen[(tool, digest)] = occurrence + 1
        return _approval_id(run_id, tool, digest, occurrence)

    return next_id


class ConversationPort(Protocol):
    """The conversation writes and reads the runner performs."""

    async def append_user_message(
        self,
        session_id: UUID,
        conversation_id: UUID,
        content: str,
        message_id: UUID | None = None,
    ) -> Any:
        """Records the user message."""
        ...

    async def complete_assistant_message(
        self,
        session_id: UUID,
        conversation_id: UUID,
        content: str,
        message_id: UUID | None = None,
        resources: tuple[ResourceAccess, ...] = (),
        tools: tuple[ToolCallRecord, ...] = (),
        token_usage: TokenUsage | None = None,
        interrupted: bool = False,
        reasoning: str = "",
    ) -> Any:
        """Records the assistant message with its whole trace."""
        ...

    async def start_run(
        self,
        session_id: UUID,
        conversation_id: UUID,
        message_id: UUID,
        run_id: UUID | None = None,
    ) -> Any:
        """Registers the run."""
        ...

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
        ...

    async def decide_approval(
        self,
        session_id: UUID,
        conversation_id: UUID,
        run_id: UUID,
        approval_id: UUID,
        approved: bool,
    ) -> None:
        """Records a decision."""
        ...

    async def finish_run(
        self,
        session_id: UUID,
        conversation_id: UUID,
        run_id: UUID,
        status: RunStatus,
        error: str | None = None,
    ) -> None:
        """Finalises the run."""
        ...

    async def list_messages(
        self,
        session_id: UUID,
        conversation_id: UUID,
        limit: int | None = None,
        offset: int = 0,
        newest_first: bool = False,
    ) -> Any:
        """Returns the stored messages, used to replay the history."""
        ...


@dataclass(frozen=True)
class RunRequest:
    """Everything one run needs from its caller."""

    conversation_id: UUID
    """Conversation the run belongs to."""
    session_id: UUID
    """Session the run writes with."""
    user_id: UUID
    """User the run acts for."""
    tenant_id: UUID | None
    """Tenant the run acts in, or ``None``."""
    content: str
    """User message that starts the run."""
    provider_id: UUID | None = None
    """Provider asked for explicitly, or ``None`` to use the fallback chain."""
    auto_approve: bool = False
    """Whether destructive tools run without asking for a decision."""
    page_context: str | None = None
    """Where the reader is in the product, spliced into the system prompt.

    The chat panel sends the page it has open (for example ``Data catalog /
    catalog crm / table contacts`` plus its path) with every prompt. It is not
    stored with the user message: it belongs to the turn, not to the transcript.
    """
    context: Mapping[str, str] = field(default_factory=dict)
    """Values approval rules may require, for example ``tenant_env``."""
    history: tuple[tuple[str, str], ...] | None = None
    """Explicit ``(role, content)`` history of an edited message.

    A regenerated run replays the history the edit use case read from the
    aggregate, so it never waits for the projection and never records the same
    user message twice. ``None`` means the normal path: load the stored history
    and append ``content`` as a new user message.
    """


class RunRecorder:
    """Collects the trace of one run and forwards it to an optional observer."""

    def __init__(
        self,
        conversation: ConversationPort,
        request: RunRequest,
        run_id: UUID,
        observer: RunObserver | None,
    ) -> None:
        """Stores the conversation port, the run identity and the downstream."""
        self._conversation = conversation
        self._request = request
        self._run_id = run_id
        self._observer = observer
        self._log = get_logger("agent.recorder")
        self.calls: list[ToolCall] = []
        """Every tool call of the run, in call order."""
        self.accessed: list[ResourceAccess] = []
        """Every resource read of the run, in read order."""
        self.approvals: list[ApprovalRequest] = []
        """Every approval the run requested."""
        self.usage = TokenUsage()
        """Token accounting of the run."""
        self.max_tool_calls = 0
        """Budget applied to the tool calls."""
        self.started_tool_calls = 0
        """Number of tool calls that already started; the budget counts these."""
        self.last_answer = ""
        """Text of the last non-empty model answer seen on the stream."""
        self.thinking = ""
        """Thinking the model streamed, capped by ``max_thinking_chars``."""
        self.max_thinking_chars = 0
        """Cap applied to :attr:`thinking`; ``0`` keeps everything."""

    async def message_started(self, *, run_id: UUID, message_id: UUID) -> None:
        """Forwards the start of the assistant message."""
        if self._observer is not None:
            await self._observer.message_started(run_id=run_id, message_id=message_id)

    async def token(self, *, run_id: UUID, delta: str) -> None:
        """Forwards one streamed token."""
        if self._observer is not None:
            await self._observer.token(run_id=run_id, delta=delta)

    async def reasoning(self, *, run_id: UUID, delta: str) -> None:
        """Accumulates one streamed thinking chunk and forwards it."""
        room = self.max_thinking_chars - len(self.thinking)
        if room > 0:
            self.thinking += delta[:room]
        if self._observer is not None:
            await self._observer.reasoning(run_id=run_id, delta=delta)

    def absorb_reasoning(self, text: str) -> None:
        """Keeps the thinking of a model that did not stream it token by token.

        The graph calls the model with ``ainvoke``, so a provider that only
        reports its thinking on the final message never reaches
        :meth:`reasoning`. Streamed thinking wins when it already arrived, so
        the same text is not counted twice.
        """
        if not text or self.thinking:
            return
        room = self.max_thinking_chars - len(self.thinking)
        if room > 0:
            self.thinking += text[:room]

    async def tool_started(self, *, run_id: UUID, call: ToolCall) -> None:
        """Counts the call against the budget and forwards it.

        The budget counts *starts*: two calls that begin before either finishes
        must both consume budget, which ``len(self.calls)`` cannot see because
        ``calls`` is appended on completion.
        """
        self.started_tool_calls += 1
        if self.max_tool_calls and self.started_tool_calls > self.max_tool_calls:
            msg = f"run {self._run_id} exceeded its {self.max_tool_calls} tool calls"
            raise ToolBudgetExceededError(msg)
        if self._observer is not None:
            await self._observer.tool_started(run_id=run_id, call=call)

    async def tool_finished(self, *, run_id: UUID, call: ToolCall) -> None:
        """Records the finished call and forwards it."""
        self.calls.append(call)
        if self._observer is not None:
            await self._observer.tool_finished(run_id=run_id, call=call)

    async def resource_read(self, *, run_id: UUID, access: ResourceAccess) -> None:
        """Records the resource read and forwards it."""
        self.accessed.append(access)
        if self._observer is not None:
            await self._observer.resource_read(run_id=run_id, access=access)

    async def approval_required(
        self,
        *,
        run_id: UUID,
        approval: ApprovalRequest,
    ) -> None:
        """Persists the pending approval and forwards it.

        A resumed run re-executes the paused tool, which asks for the decision
        again with the same id. The aggregate already holds it, so that second
        ask is a replay rather than a new decision and must not reach the client.
        """
        try:
            await self._conversation.request_approval(
                self._request.session_id,
                self._request.conversation_id,
                run_id,
                approval.tool,
                approval.args_hash,
                approval.reason,
                approval.approval_id,
            )
        except ApprovalAlreadyDecidedError:
            self._log.debug(
                "agent.approval.replayed",
                approval_id=str(approval.approval_id),
                tool=approval.tool,
            )
            return
        self.approvals.append(approval)
        if self._observer is not None:
            await self._observer.approval_required(run_id=run_id, approval=approval)

    async def approval_resolved(
        self,
        *,
        run_id: UUID,
        approval_id: UUID,
        approved: bool,
    ) -> None:
        """Forwards the decision."""
        if self._observer is not None:
            await self._observer.approval_resolved(
                run_id=run_id,
                approval_id=approval_id,
                approved=approved,
            )

    async def approval_decided(
        self,
        run_id: UUID,
        approval_id: UUID,
        approved: bool,
    ) -> None:
        """Records a decision the graph applied without pausing again.

        The route usually recorded the human answer before the resume, so this
        write is a replay rather than an error. The event is forwarded either way:
        it is what tells the browser that the card is settled, and a card that
        never hears it is rendered as pending again.
        """
        try:
            await self._conversation.decide_approval(
                self._request.session_id,
                self._request.conversation_id,
                run_id,
                approval_id,
                approved,
            )
        except ApprovalAlreadyDecidedError:
            self._log.debug(
                "agent.approval.decision.replayed",
                approval_id=str(approval_id),
                approved=approved,
            )
        await self.approval_resolved(
            run_id=run_id,
            approval_id=approval_id,
            approved=approved,
        )

    async def message_completed(self, *, run: AgentRun) -> None:
        """Forwards the completed assistant message."""
        if self._observer is not None:
            await self._observer.message_completed(run=run)

    async def failed(self, *, run_id: UUID, error: str) -> None:
        """Forwards the failure."""
        if self._observer is not None:
            await self._observer.failed(run_id=run_id, error=error)

    def add_usage(self, prompt_tokens: int, completion_tokens: int) -> None:
        """Accumulates the usage of one model call."""
        self.usage = TokenUsage(
            input_tokens=self.usage.input_tokens + prompt_tokens,
            output_tokens=self.usage.output_tokens + completion_tokens,
        )


class AgentRunner:
    """Builds the graph, streams it and keeps the conversation truthful."""

    def __init__(
        self,
        *,
        client: McpClient,
        settings: AgentRuntimeSettings,
        conversation: ConversationPort,
        chat_model_factory: ChatModelFactory,
        checkpointer: BaseCheckpointSaver[Any] | None = None,
        tracing: MlflowSettings | None = None,
    ) -> None:
        """Stores the transport, the policy settings and the ports."""
        self._client = client
        self._settings = settings
        self._conversation = conversation
        self._chat_model_factory = chat_model_factory
        self._checkpointer = checkpointer
        self._tracing = tracing or MlflowSettings()
        self._policy = ApprovalPolicy(settings)
        self._catalogue: str | None = None
        self._tools: list[Any] | None = None
        self._log = get_logger("agent.runtime")

    async def warm_up(self) -> str:
        """Fetches the resource and prompt catalogue used by the system prompt.

        The catalogue is loaded on first use, so a deployment that never runs an
        agent never pays for the three extra MCP calls.

        Returns:
            The rendered catalogue, or an empty string when the server has none.
        """
        return await self._ensure_catalogue()

    async def _ensure_catalogue(self) -> str:
        """Returns the catalogue, fetching it once per runner."""
        if self._catalogue is not None:
            return self._catalogue
        resources = await self._client.list_resources()
        templates = await self._client.list_resource_templates()
        prompts = await self._client.list_prompts()
        sections = [
            build_catalogue(resources, templates),
            build_prompt_catalogue(prompts),
        ]
        self._catalogue = "\n\n".join(section for section in sections if section)
        return self._catalogue

    async def _list_tools(self) -> list[Any]:
        """Returns the MCP tool definitions, fetched once per runner."""
        if self._tools is None:
            self._tools = list(await self._client.list_tools())
        return self._tools

    async def run(
        self,
        request: RunRequest,
        observer: RunObserver | None = None,
        *,
        run_id: UUID | None = None,
        message_id: UUID | None = None,
    ) -> AgentRun:
        """Records the user message, starts the run and executes the graph.

        Args:
            request: The user message and the identity it runs under.
            observer: Optional incremental sink, typically the SSE streamer.
            run_id: Caller-supplied run id, or ``None`` to generate one.
            message_id: Caller-supplied assistant message id, or ``None``.

        Returns:
            The finalised run.
        """
        resolved_run_id = run_id or uuid4()
        resolved_message_id = message_id or uuid4()
        if request.history is not None:
            history = _history_messages(request.history, self._settings.history_limit)
        else:
            history = await self._load_history(request)
            await self._conversation.append_user_message(
                request.session_id,
                request.conversation_id,
                request.content,
            )
        await self._conversation.start_run(
            request.session_id,
            request.conversation_id,
            resolved_message_id,
            resolved_run_id,
        )
        self._log.info(
            "agent.run.start",
            run_id=str(resolved_run_id),
            conversation_id=str(request.conversation_id),
        )
        return await self._execute(
            request,
            resolved_run_id,
            resolved_message_id,
            observer,
            resume=None,
            history=history,
        )

    async def resume(
        self,
        request: RunRequest,
        *,
        run_id: UUID,
        message_id: UUID,
        approval_id: UUID,
        approved: bool,
        observer: RunObserver | None = None,
    ) -> AgentRun:
        """Resumes a run that is paused on an approval.

        Args:
            request: The identity the run continues with.
            run_id: Run that is paused.
            message_id: Assistant message the run produces.
            approval_id: Approval that was decided.
            approved: Whether the tool call may run.
            observer: Optional incremental sink.

        Returns:
            The finalised run.
        """
        await self._conversation.decide_approval(
            request.session_id,
            request.conversation_id,
            run_id,
            approval_id,
            approved,
        )
        self._log.info(
            "agent.run.resume",
            run_id=str(run_id),
            approval_id=str(approval_id),
            approved=approved,
        )
        decision = ApprovalDecision(approved=approved)
        return await self._execute(
            request,
            run_id,
            message_id,
            observer,
            resume=decision,
            history=None,
        )

    async def _load_history(self, request: RunRequest) -> list[BaseMessage]:
        """Returns the previous messages of the conversation, oldest first.

        The checkpoint only holds the run it belongs to, so the conversation
        store is what gives a new run its context. The rows carry text only, so a
        replayed history can never contain a tool call without its result. Blank
        rows (an interrupted run that produced no answer) are dropped for the
        same reason: a provider rejects an empty assistant turn.

        Args:
            request: The run the history belongs to.

        Returns:
            At most ``history_limit`` previous messages.
        """
        limit = self._settings.history_limit
        if limit <= 0:
            return []
        rows = await self._conversation.list_messages(
            request.session_id,
            request.conversation_id,
            limit=limit,
            newest_first=True,
        )
        return [_as_message(row) for row in rows if _has_text(row)]

    async def _execute(
        self,
        request: RunRequest,
        run_id: UUID,
        message_id: UUID,
        observer: RunObserver | None,
        resume: ApprovalDecision | None,
        history: list[BaseMessage] | None,
    ) -> AgentRun:
        """Runs or resumes the graph, recording the run in the tracer."""
        with trace_run(
            self._tracing,
            run_id=str(run_id),
            inputs={
                "conversation_id": str(request.conversation_id),
                "mode": "resume" if resume is not None else "run",
            },
        ) as active_run:
            run = await self._execute_inner(
                request,
                run_id,
                message_id,
                observer,
                resume,
                history,
            )
            log_outcome(
                active_run,
                status=run.status,
                tool_calls=len(run.tool_calls),
                tokens=run.usage.total_tokens,
            )
            return run

    async def _execute_inner(
        self,
        request: RunRequest,
        run_id: UUID,
        message_id: UUID,
        observer: RunObserver | None,
        resume: ApprovalDecision | None,
        history: list[BaseMessage] | None,
    ) -> AgentRun:
        """Runs or resumes the graph and always closes the run it started.

        Every exit path has to leave the run in a terminal status, or the
        conversation stays blocked by its own "run in flight" rule. Two paths
        used to skip that: the task being cancelled (client disconnect, reload,
        shutdown) and a failure while the model, the tools or the prompt are
        built, which happened before the graph's own ``try``. Both are finalised
        here before the error propagates.
        """
        recorder = RunRecorder(self._conversation, request, run_id, observer)
        recorder.max_tool_calls = self._settings.limits.max_tool_calls
        recorder.max_thinking_chars = self._settings.limits.max_reasoning_chars
        try:
            return await self._execute_graph(
                request,
                run_id,
                message_id,
                observer,
                resume,
                history,
                recorder,
            )
        except asyncio.CancelledError:
            await self._finalise_cancelled(request, run_id, message_id, recorder)
            raise
        except Exception as exc:
            self._log.exception("agent.run.failed", run_id=str(run_id))
            await self._abandon_run(request, run_id, "failed", str(exc))
            raise

    async def _execute_graph(
        self,
        request: RunRequest,
        run_id: UUID,
        message_id: UUID,
        observer: RunObserver | None,
        resume: ApprovalDecision | None,
        history: list[BaseMessage] | None,
        recorder: RunRecorder,
    ) -> AgentRun:
        """Runs the graph and persists the outcome of a run that was started."""
        chat = await self._chat_model_factory(
            request.provider_id,
            request.user_id,
            request.tenant_id,
        )
        tools = await self._build_tools(request, run_id, recorder)
        graph = self._build_graph(chat, tools, await self._system_prompt(request.page_context))
        config: RunnableConfig = {
            "configurable": {
                "thread_id": _thread_id(request.conversation_id, run_id),
                "run_id": str(run_id),
            },
            "recursion_limit": max(10, self._settings.limits.max_tool_calls * 2),
        }
        payload: Any = (
            resume_command(resume)
            if resume is not None
            else {
                "messages": [
                    *(history or []),
                    HumanMessage(content=request.content),
                ],
            }
        )
        await recorder.message_started(run_id=run_id, message_id=message_id)
        status: RunStatus = "completed"
        error: str | None = None
        snapshot: Any = None
        if resume is not None and self._checkpointer is not None:
            before = await graph.aget_state(config)
            recorder.calls.extend(_restore_calls(getattr(before, "values", None), self._settings))
        try:
            async with self._client.lifespan():
                await self._stream(graph, payload, config, recorder, run_id)
            snapshot = await graph.aget_state(config) if self._checkpointer else None
            self._absorb_state_usage(recorder, snapshot)
            self._check_token_budget(recorder)
        except TimeoutError:
            status = "interrupted"
            error = "the run exceeded its wall-clock budget"
            await recorder.failed(run_id=run_id, error=error)
        except Exception as exc:
            status = "failed"
            error = str(exc)
            self._log.exception("agent.run.failed", run_id=str(run_id))
            await recorder.failed(run_id=run_id, error=error)
        snapshot = await graph.aget_state(config) if self._checkpointer else None
        interrupts = list(getattr(snapshot, "interrupts", ()) or ())
        answer = _final_text(getattr(snapshot, "values", None), turn=request.content)
        if not answer:
            answer = recorder.last_answer
        if not answer and status == "completed":
            # Never reuse a replayed message: a stale answer looks like the
            # assistant has forgotten the conversation, which is worse than
            # admitting the turn produced nothing.
            answer = NO_ANSWER_TEXT
        if interrupts and status == "completed":
            self._log.info("agent.run.awaiting_approval", run_id=str(run_id))
            run = AgentRun(
                run_id=run_id,
                conversation_id=request.conversation_id,
                message_id=message_id,
                status="awaiting_approval",
                final_answer=answer,
                reasoning=recorder.thinking,
                tool_calls=list(recorder.calls),
                resources_accessed=list(recorder.accessed),
                usage=recorder.usage,
                approvals=list(recorder.approvals),
            )
            # The pause is a terminal state of *this* stream: the client has to
            # learn it, or it waits for a `done` that only a resume would send.
            await recorder.message_completed(run=run)
            return run
        await self._conversation.complete_assistant_message(
            request.session_id,
            request.conversation_id,
            answer,
            message_id,
            tuple(recorder.accessed),
            tuple(call.as_record() for call in recorder.calls),
            recorder.usage,
            status != "completed",
            reasoning=recorder.thinking,
        )
        await self._conversation.finish_run(
            request.session_id,
            request.conversation_id,
            run_id,
            _terminal_status(status),
            error,
        )
        run = AgentRun(
            run_id=run_id,
            conversation_id=request.conversation_id,
            message_id=message_id,
            status=status,
            final_answer=answer,
            reasoning=recorder.thinking,
            tool_calls=list(recorder.calls),
            resources_accessed=list(recorder.accessed),
            usage=recorder.usage,
            approvals=list(recorder.approvals),
            error=error,
        )
        await recorder.message_completed(run=run)
        self._log.info("agent.run.done", run_id=str(run_id), status=status)
        return run

    async def _finalise_cancelled(
        self,
        request: RunRequest,
        run_id: UUID,
        message_id: UUID,
        recorder: RunRecorder,
    ) -> None:
        """Closes a run whose task was cancelled.

        A cancelled task is the one path that never reaches ``finish_run`` on its
        own: the client disconnected or the process is shutting down. The write
        runs on its own task and is shielded, because the surrounding task is
        already being cancelled and a second cancel must not lose it.
        """
        reason = "the stream was closed before the run finished"
        await recorder.failed(run_id=run_id, error=reason)
        write = asyncio.ensure_future(
            self._abandon_with_message(request, run_id, message_id, recorder, reason)
        )
        try:
            await asyncio.shield(write)
        except asyncio.CancelledError:
            # The write keeps going on its own task; nothing else to do here.
            self._log.info("agent.run.cancelled", run_id=str(run_id))

    async def _abandon_with_message(
        self,
        request: RunRequest,
        run_id: UUID,
        message_id: UUID,
        recorder: RunRecorder,
        reason: str,
    ) -> None:
        """Records the partial answer and marks the run interrupted."""
        try:
            await self._conversation.complete_assistant_message(
                request.session_id,
                request.conversation_id,
                recorder.last_answer,
                message_id,
                tuple(recorder.accessed),
                tuple(call.as_record() for call in recorder.calls),
                recorder.usage,
                True,
                reasoning=recorder.thinking,
            )
        except Exception:
            self._log.exception("agent.run.abandon.message.failed", run_id=str(run_id))
        await self._abandon_run(request, run_id, "interrupted", reason)

    async def _abandon_run(
        self,
        request: RunRequest,
        run_id: UUID,
        status: RunStatus,
        error: str,
    ) -> None:
        """Moves a run out of ``running`` when the normal path could not.

        Failures are swallowed: the run is already broken, and the original error
        is what the caller must see.
        """
        try:
            await self._conversation.finish_run(
                request.session_id,
                request.conversation_id,
                run_id,
                status,
                error,
            )
            self._log.info("agent.run.abandoned", run_id=str(run_id), status=status)
        except Exception:
            self._log.exception("agent.run.abandon.failed", run_id=str(run_id))

    async def _stream(
        self,
        graph: Any,
        payload: Any,
        config: RunnableConfig,
        recorder: RunRecorder,
        run_id: UUID,
    ) -> None:
        """Streams the graph and forwards tokens and usage to the recorder."""
        async with asyncio.timeout(self._settings.limits.max_wall_clock_seconds):
            async for event in graph.astream_events(payload, config=config, version="v2"):
                kind = event.get("event")
                if kind == "on_chat_model_stream":
                    chunk = event.get("data", {}).get("chunk")
                    reasoning, content = _split_delta(chunk)
                    if reasoning:
                        await recorder.reasoning(run_id=run_id, delta=reasoning)
                    if content:
                        await recorder.token(run_id=run_id, delta=content)
                elif kind == "on_chat_model_end":
                    output = event.get("data", {}).get("output")
                    reasoning, content = _split_content(getattr(output, "content", ""))
                    if content.strip():
                        recorder.last_answer = content
                    recorder.absorb_reasoning(reasoning)
                    metadata = getattr(output, "usage_metadata", None) or {}
                    recorder.add_usage(
                        int(metadata.get("input_tokens", 0) or 0),
                        int(metadata.get("output_tokens", 0) or 0),
                    )
                    self._check_token_budget(recorder)

    def _check_token_budget(self, recorder: RunRecorder) -> None:
        """Raises when the run already spent more tokens than allowed.

        Args:
            recorder: The recorder holding the accumulated usage.

        Raises:
            TokenBudgetExceededError: If the usage exceeds ``token_budget``.
        """
        budget = self._settings.limits.token_budget
        if budget <= 0:
            return
        spent = recorder.usage.total_tokens
        if spent > budget:
            msg = f"the run used {spent} tokens, above its token budget of {budget}"
            raise TokenBudgetExceededError(msg)

    def _absorb_state_usage(self, recorder: RunRecorder, snapshot: Any) -> None:
        """Adds the usage of the final state when the stream reported none.

        Some providers (and fake models) drop ``usage_metadata`` from the stream
        events but keep it on the message, so the state is a fallback rather than
        a second source of truth.

        Args:
            recorder: The recorder holding the accumulated usage.
            snapshot: Final graph state, or ``None`` without a checkpointer.
        """
        if snapshot is None or recorder.usage.total_tokens:
            return
        messages = list((getattr(snapshot, "values", None) or {}).get("messages") or [])
        prompt = 0
        completion = 0
        for message in messages:
            metadata = getattr(message, "usage_metadata", None) or {}
            prompt += int(metadata.get("input_tokens", 0) or 0)
            completion += int(metadata.get("output_tokens", 0) or 0)
        if prompt or completion:
            recorder.add_usage(prompt, completion)

    def _build_graph(
        self,
        chat: BaseChatModel,
        tools: list[BaseTool],
        system_prompt: str,
    ) -> Any:
        """Builds the agent graph: one model node, one tool node, a loop.

        ``interrupt`` inside a tool pauses the graph, and the checkpointer keeps
        the paused state, so a resumed run continues where it stopped.

        Args:
            chat: Chat model the run uses.
            tools: Tools the model may call.
            system_prompt: Instructions prepended to every model call.

        Returns:
            The compiled graph, bound to the configured checkpointer.
        """
        model = chat.bind_tools(tools) if tools else chat
        builder = StateGraph(_AgentState)

        async def agent_node(state: _AgentState) -> dict[str, Any]:
            base: list[BaseMessage] = list(state["messages"])
            if system_prompt:
                base = [SystemMessage(content=system_prompt), *base]
            produced: list[BaseMessage] = []
            nudges = int(state.get("nudges", 0))
            while True:
                answer = await model.ainvoke([*base, *produced])
                produced.append(answer)
                if not _needs_nudge(answer, nudges):
                    break
                nudges += 1
                self._log.info("agent.run.empty_turn", nudges=nudges)
                produced.append(HumanMessage(content=EMPTY_TURN_NUDGE))
            return {"messages": produced, "nudges": nudges}

        builder.add_node("agent", agent_node)
        builder.add_edge(START, "agent")
        if tools:
            builder.add_node("tools", ToolNode(tools))
            builder.add_conditional_edges(
                "agent",
                _next_step,
                {"tools": "tools", "end": END},
            )
            builder.add_edge("tools", "agent")
        else:
            builder.add_edge("agent", END)
        return builder.compile(checkpointer=self._checkpointer)

    async def _build_tools(
        self,
        request: RunRequest,
        run_id: UUID,
        recorder: RunRecorder,
    ) -> list[BaseTool]:
        """Builds the LangChain tools of the run."""
        executor = ToolExecutor(
            self._client.call_tool,
            self._policy,
            self._settings,
            observer=recorder,
            run_id=run_id,
            auto_approve=request.auto_approve,
            approval_ids=_approval_ids(run_id),
            approval_decided=recorder.approval_decided,
        )
        context = dict(request.context)
        tools: list[BaseTool] = [
            to_langchain_tool(tool, executor, context=context)
            for tool in await self._list_tools()
            if self._settings.exposes(tool.name)
        ]
        reader = ResourceReader(
            self._client.read_resource,
            self._settings,
            observer=recorder,
            run_id=run_id,
        )
        if self._settings.exposes(READ_RESOURCE_TOOL):
            tools.append(build_resource_tool(reader))
        if self._settings.exposes(RENDER_PROMPT_TOOL):
            tools.append(build_prompt_tool(self._client.get_prompt))
        return tools

    async def _system_prompt(self, page_context: str | None = None) -> str:
        """Composes the system prompt from the catalogue and the conventions.

        Args:
            page_context: Page the reader has open, appended as the subject of
                the question when the caller sent one.

        Returns:
            The instructions prepended to every model call.
        """
        await self._ensure_catalogue()
        sections = [
            "You operate the ETLAlchemy metadata service through its MCP tools.",
            "Prefer the parameterised read tools and the resource URIs below over guessing ids.",
            "Tool errors start with a bracketed category: [not_found] and [conflict] mean "
            "correct the arguments and retry with different input; [forbidden] and "
            "[unauthorized] mean stop and tell the user; [internal] may be retried once.",
            "Destructive tools need an explicit human approval; never claim a change "
            "succeeded when the tool answered [denied].",
            "Address an object you mention as a URN so the chat can link it: "
            "urn:catalog/<catalog_id>[/schema/<schema_id>[/table/<table_id>"
            "[/field/<column_name>]]], urn:vocabulary/<domain_id>[/term/<term_id>] "
            "and urn:semantic/<model_id>[/entity/<entity_name>]. Use the ids the tools "
            "returned and never invent one.",
        ]
        if self._catalogue:
            sections.append("Available resources and prompts:\n" + self._catalogue)
        if page_context:
            sections.append(
                "The reader has this page open in the browser; treat it as the subject "
                "of the request unless the message says otherwise:\n"
                + page_context[:PAGE_CONTEXT_CHARS]
            )
        if self._settings.system_prompt:
            sections.append(self._settings.system_prompt)
        return "\n\n".join(sections)


def _final_text(values: Mapping[str, Any] | None, *, turn: str) -> str:
    """Returns the answer text the current turn produced.

    The state carries the replayed history in front of the current turn, so a
    scan that ignores the boundary returns an old answer whenever the model ends
    without text - which reads as if the assistant forgot the conversation.

    Args:
        values: Values of the graph state.
        turn: Content of the user message that opened the current turn.

    Returns:
        The text of the last non-empty assistant message of this turn, or ``""``.
    """
    messages: list[BaseMessage] = list((values or {}).get("messages") or [])
    for message in reversed(messages[_turn_start(messages, turn) :]):
        if isinstance(message, AIMessage):
            text = _message_text(message)
            if text.strip():
                return text
    return ""


def _turn_start(messages: list[BaseMessage], turn: str) -> int:
    """Returns the index after the user message that opened the current turn."""
    for index in range(len(messages) - 1, -1, -1):
        message = messages[index]
        if isinstance(message, HumanMessage) and message.content == turn:
            return index + 1
    for index in range(len(messages) - 1, -1, -1):
        if isinstance(messages[index], HumanMessage):
            return index + 1
    return len(messages)


def _needs_nudge(message: BaseMessage, nudges: int) -> bool:
    """Returns whether a model answer ended the turn without saying anything.

    A provider that spends its whole output budget on thinking answers with an
    empty message and no tool call, which ends the loop mid-task. Asking once
    more turns that silent stop into an answer.

    Args:
        message: The message the model just returned.
        nudges: How often this run already asked it to continue.

    Returns:
        ``True`` when the model should be asked to continue.
    """
    if nudges >= MAX_EMPTY_TURNS:
        return False
    if getattr(message, "tool_calls", None):
        return False
    return not _message_text(message).strip()


def _message_text(message: Any) -> str:
    """Returns the answer text of one message, without its thinking."""
    return _split_content(getattr(message, "content", ""))[1]


def _block_text(block: Any) -> str:
    """Returns the text of one content block, or an empty string.

    A reasoning block may carry its text in ``text`` or, as the Databricks
    gateway does, in a list of ``summary_text`` items under ``summary``.
    """
    if isinstance(block, str):
        return block
    if isinstance(block, Mapping):
        for key in ("text", "reasoning", "thinking", "content"):
            value = block.get(key)
            if isinstance(value, str):
                return value
        summary = block.get("summary")
        if isinstance(summary, Mapping):
            return _block_text(summary)
        if isinstance(summary, (list, tuple)):
            return "".join(_block_text(part) for part in summary)
    return ""


def _split_content(content: Any) -> tuple[str, str]:
    """Splits model content into its reasoning and its answer text.

    A provider may return a plain string or a list that mixes plain strings,
    text blocks and reasoning blocks. Reasoning blocks (including the
    ``reasoning``/``summary`` shape of the Databricks gateway) never belong to
    the answer.

    Args:
        content: ``AIMessage.content`` of a model or one streamed chunk.

    Returns:
        The reasoning text and the answer text; both may be empty.
    """
    reasoning: list[str] = []
    answer: list[str] = []
    if isinstance(content, str):
        answer.append(content)
    elif isinstance(content, (list, tuple)):
        for block in content:
            kind = str(block.get("type", "")) if isinstance(block, Mapping) else ""
            if kind in REASONING_BLOCK_TYPES:
                reasoning.append(_block_text(block))
            else:
                answer.append(_block_text(block))
    return "".join(reasoning), "".join(answer)


def _split_delta(chunk: Any) -> tuple[str, str]:
    """Splits one streamed model chunk into its reasoning and its answer text.

    Providers disagree on where the thinking is: Anthropic-style models send
    content blocks typed ``reasoning``, DeepSeek sends ``reasoning_content`` in
    ``additional_kwargs`` and everybody else sends a plain string. A block list
    wins over the extra field, so a provider that reports both is not counted
    twice.

    Args:
        chunk: ``AIMessageChunk`` the model emitted.

    Returns:
        The reasoning text and the answer text of this chunk; both may be empty.
    """
    reasoning, answer = _split_content(getattr(chunk, "content", ""))
    extra = getattr(chunk, "additional_kwargs", None)
    if not reasoning and isinstance(extra, Mapping):
        reasoning = _block_text(extra.get("reasoning_content"))
    return reasoning, answer


def _restore_calls(
    values: Mapping[str, Any] | None,
    settings: AgentRuntimeSettings,
) -> list[ToolCall]:
    """Rebuilds the tool calls a paused run already made.

    A resumed run starts a new recorder, so without this the persisted trace
    would only contain the calls made after the approval and the pre-approval
    call would vanish from the message history. The arguments and the result of
    the restored call are still in the checkpoint, so the tool drawer keeps the
    same content after the resume.

    Args:
        values: Messages of the graph state the run paused in.
        settings: Limits and redaction keys of the previews.

    Returns:
        One record per call, in call order.
    """
    messages: list[BaseMessage] = list((values or {}).get("messages") or [])
    statuses: dict[str, str] = {}
    outputs: dict[str, str] = {}
    for message in messages:
        if isinstance(message, ToolMessage):
            call_id = str(getattr(message, "tool_call_id", ""))
            statuses[call_id] = str(getattr(message, "status", "ok"))
            content = message.content
            outputs[call_id] = content if isinstance(content, str) else ""
    restored: list[ToolCall] = []
    for message in messages:
        for call in getattr(message, "tool_calls", None) or []:
            call_id = str(call.get("id") or "")
            arguments = call.get("args") or {}
            restored.append(
                ToolCall(
                    tool=str(call.get("name") or ""),
                    args_hash=args_hash(arguments),
                    status=statuses.get(call_id, "ok"),
                    args_json=preview_json(
                        redact_arguments(arguments, settings.redact_argument_keys),
                        settings.limits.max_tool_args_chars,
                    ),
                    result_preview=preview_text(
                        outputs.get(call_id, ""),
                        settings.limits.max_tool_result_preview_chars,
                    ),
                ),
            )
    return restored


def _terminal_status(status: RunStatus) -> RunStatus:
    """Keeps ``completed`` and ``interrupted`` and collapses the rest to ``failed``."""
    if status == "completed":
        return "completed"
    if status == "interrupted":
        return "interrupted"
    return "failed"


def _as_message(row: Any) -> BaseMessage:
    """Converts a stored message row into the message the graph replays."""
    content = getattr(row, "content", "")
    if getattr(row, "role", "user") == "assistant":
        return AIMessage(content=content)
    return HumanMessage(content=content)


def _history_messages(
    pairs: tuple[tuple[str, str], ...],
    limit: int,
) -> list[BaseMessage]:
    """Converts explicit ``(role, content)`` pairs into replay messages.

    Blank rows are dropped for the same reason as in the stored history: a
    provider rejects an empty assistant turn.
    """
    if limit <= 0:
        return []
    selected = [pair for pair in pairs if pair[1].strip()][-limit:]
    return [
        AIMessage(content=content) if role == "assistant" else HumanMessage(content=content)
        for role, content in selected
    ]


def _has_text(row: Any) -> bool:
    """Returns whether a stored message carries text worth replaying."""
    return str(getattr(row, "content", "")).strip() != ""


class _AgentState(TypedDict, total=False):
    """State of the agent graph: the message list the framework accumulates."""

    messages: Annotated[list[BaseMessage], add_messages]
    nudges: int
    """How often this run asked the model to answer after an empty turn."""


def _next_step(state: _AgentState) -> str:
    """Returns the next node: the tools when the model asked for one, else the end."""
    messages = state.get("messages") or []
    last = messages[-1] if messages else None
    if isinstance(last, AIMessage) and last.tool_calls:
        return "tools"
    return "end"
