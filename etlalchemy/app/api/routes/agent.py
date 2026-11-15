"""HTTP routes of the agent: LLM providers, conversations and SSE runs."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from uuid import UUID, uuid4

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.responses import StreamingResponse

from etlalchemy.agent.factory import AgentFactory
from etlalchemy.agent.results import AgentRun
from etlalchemy.agent.runtime import RunRequest
from etlalchemy.agent.service.streaming import RunStream
from etlalchemy.app.api.dependencies.auth import get_bearer_token, get_session_id
from etlalchemy.app.bootstrap import Container
from etlalchemy.app.schemas.agent import (
    ApprovalDecisionBody,
    ApprovalResponse,
    ConversationCreate,
    ConversationPatch,
    ConversationResponse,
    CredentialRotateRequest,
    MessageCreate,
    MessageResponse,
    ProviderCreate,
    ProviderDefaultRequest,
    ProviderDetailResponse,
    ProviderPatch,
    ProviderResponse,
    ProviderShareRequest,
    RunResponse,
    RunResultResponse,
)
from etlalchemy.app.schemas.common import OkResponse
from etlalchemy.conversation.aggregates.errors import (
    ApprovalAlreadyDecidedError,
    ConversationError,
    UnknownApprovalError,
    UnknownConversationError,
    UnknownMessageError,
    UnknownRunError,
)
from etlalchemy.conversation.application import ConversationApplication
from etlalchemy.iam.aggregates.errors import (
    AuthenticationError,
    PermissionDeniedError,
)
from etlalchemy.llm_config.aggregates.errors import (
    InvalidSharingError,
    LlmConfigError,
    UnknownProviderError,
    UnknownShareTargetError,
)
from etlalchemy.llm_config.application import LlmConfigApplication

router = APIRouter(prefix="/agent", tags=["agent"])

SSE_MEDIA_TYPE = "text/event-stream"
"""Media type of the streaming endpoints."""


def add_exception_handlers(app: object) -> None:
    """Registers the agent exception handlers on the HTTP application.

    Args:
        app: The FastAPI application to register the handlers on.
    """
    handlers: list[tuple[type[Exception], int]] = [
        (AuthenticationError, status.HTTP_401_UNAUTHORIZED),
        (PermissionDeniedError, status.HTTP_403_FORBIDDEN),
        (
            UnknownProviderError,
            status.HTTP_404_NOT_FOUND,
        ),
        (UnknownShareTargetError, status.HTTP_404_NOT_FOUND),
        (UnknownConversationError, status.HTTP_404_NOT_FOUND),
        (UnknownMessageError, status.HTTP_404_NOT_FOUND),
        (UnknownRunError, status.HTTP_404_NOT_FOUND),
        (UnknownApprovalError, status.HTTP_404_NOT_FOUND),
        (InvalidSharingError, status.HTTP_400_BAD_REQUEST),
        (ApprovalAlreadyDecidedError, status.HTTP_409_CONFLICT),
        (LlmConfigError, status.HTTP_409_CONFLICT),
        (ConversationError, status.HTTP_409_CONFLICT),
    ]

    def make_handler(code: int) -> object:
        async def handler(request: object, exc: Exception) -> object:
            detail = str(exc) or "request rejected"
            return _json_error(code, detail)

        return handler

    for exc_type, code in handlers:
        app.add_exception_handler(exc_type, make_handler(code))  # type: ignore[attr-defined]


def _json_error(code: int, detail: str) -> Response:
    """Builds one JSON error response."""
    return Response(
        content=json.dumps({"detail": detail}),
        status_code=code,
        media_type="application/json",
    )


# -- LLM providers ----------------------------------------------------------


@router.get("/llm-providers", response_model=list[ProviderResponse])
@inject
async def list_llm_providers(
    include_public: bool = True,
    mine_only: bool = False,
    limit: int | None = None,
    offset: int = 0,
    session_id: UUID = Depends(get_session_id),  # noqa: B008
    application: LlmConfigApplication = Depends(  # noqa: B008
        Provide[Container.llm_config_application]
    ),
) -> list[ProviderResponse]:
    """Returns the LLM providers the caller may use."""
    rows = await application.list_llm_providers(
        session_id,
        include_public=include_public,
        mine_only=mine_only,
        limit=limit,
        offset=offset,
    )
    return [ProviderResponse.from_row(row) for row in rows]


@router.post(
    "/llm-providers",
    response_model=ProviderResponse,
    status_code=status.HTTP_201_CREATED,
)
@inject
async def create_llm_provider(
    body: ProviderCreate,
    session_id: UUID = Depends(get_session_id),  # noqa: B008
    application: LlmConfigApplication = Depends(  # noqa: B008
        Provide[Container.llm_config_application]
    ),
) -> ProviderResponse:
    """Creates an LLM provider owned by the caller."""
    provider_id = await application.create_llm_provider(
        session_id,
        name=body.name,
        kind=body.kind,
        endpoint=body.endpoint,
        credential_ref=body.credential_ref,
        token=body.token,
        default_model=body.default_model,
        options=body.options,
        tenant_id=body.tenant_id,
        is_public=body.is_public,
    )
    detail = await application.created_provider_detail(provider_id)
    return ProviderDetailResponse.from_detail(detail)


@router.get("/llm-providers/{provider_id}", response_model=ProviderDetailResponse)
@inject
async def get_llm_provider(
    provider_id: UUID,
    session_id: UUID = Depends(get_session_id),  # noqa: B008
    application: LlmConfigApplication = Depends(  # noqa: B008
        Provide[Container.llm_config_application]
    ),
) -> ProviderDetailResponse:
    """Returns one LLM provider with its shares and default pointers."""
    detail = await application.get_llm_provider(session_id, provider_id)
    return ProviderDetailResponse.from_detail(detail)


@router.patch("/llm-providers/{provider_id}", response_model=OkResponse)
@inject
async def change_llm_provider(
    provider_id: UUID,
    body: ProviderPatch,
    session_id: UUID = Depends(get_session_id),  # noqa: B008
    application: LlmConfigApplication = Depends(  # noqa: B008
        Provide[Container.llm_config_application]
    ),
) -> OkResponse:
    """Changes the metadata of an LLM provider."""
    await application.change_llm_provider(
        session_id,
        provider_id,
        name=body.name,
        endpoint=body.endpoint,
        default_model=body.default_model,
        options=body.options,
    )
    return OkResponse()


@router.post("/llm-providers/{provider_id}/rotate", response_model=OkResponse)
@inject
async def rotate_llm_credential(
    provider_id: UUID,
    body: CredentialRotateRequest,
    session_id: UUID = Depends(get_session_id),  # noqa: B008
    application: LlmConfigApplication = Depends(  # noqa: B008
        Provide[Container.llm_config_application]
    ),
) -> OkResponse:
    """Replaces the credential of an LLM provider."""
    await application.rotate_llm_credential(
        session_id,
        provider_id,
        credential_ref=body.credential_ref,
        token=body.token,
    )
    return OkResponse()


@router.post("/llm-providers/{provider_id}/share", response_model=OkResponse)
@inject
async def share_llm_provider(
    provider_id: UUID,
    body: ProviderShareRequest,
    session_id: UUID = Depends(get_session_id),  # noqa: B008
    application: LlmConfigApplication = Depends(  # noqa: B008
        Provide[Container.llm_config_application]
    ),
) -> OkResponse:
    """Replaces the users and groups an LLM provider is shared with."""
    await application.share_llm_provider(
        session_id,
        provider_id,
        user_ids=body.user_ids,
        group_ids=body.group_ids,
    )
    return OkResponse()


@router.post("/llm-providers/{provider_id}/default", response_model=OkResponse)
@inject
async def set_default_llm_provider(
    provider_id: UUID,
    body: ProviderDefaultRequest,
    session_id: UUID = Depends(get_session_id),  # noqa: B008
    application: LlmConfigApplication = Depends(  # noqa: B008
        Provide[Container.llm_config_application]
    ),
) -> OkResponse:
    """Makes an LLM provider the default of one scope."""
    await application.set_default_llm_provider(
        session_id,
        provider_id,
        scope=body.scope,
        target_id=body.target_id,
    )
    return OkResponse()


@router.delete("/llm-providers/{provider_id}", status_code=status.HTTP_204_NO_CONTENT)
@inject
async def discard_llm_provider(
    provider_id: UUID,
    session_id: UUID = Depends(get_session_id),  # noqa: B008
    application: LlmConfigApplication = Depends(  # noqa: B008
        Provide[Container.llm_config_application]
    ),
) -> Response:
    """Discards an LLM provider."""
    await application.discard_llm_provider(session_id, provider_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# -- conversations ----------------------------------------------------------


@router.get("/conversations", response_model=list[ConversationResponse])
@inject
async def list_conversations(
    limit: int | None = None,
    offset: int = 0,
    session_id: UUID = Depends(get_session_id),  # noqa: B008
    application: ConversationApplication = Depends(  # noqa: B008
        Provide[Container.conversation_application]
    ),
) -> list[ConversationResponse]:
    """Returns the conversations of the caller."""
    rows = await application.list_conversations(session_id, limit=limit, offset=offset)
    return [ConversationResponse.from_row(row) for row in rows]


@router.post(
    "/conversations",
    response_model=ConversationResponse,
    status_code=status.HTTP_201_CREATED,
)
@inject
async def create_conversation(
    body: ConversationCreate,
    session_id: UUID = Depends(get_session_id),  # noqa: B008
    application: ConversationApplication = Depends(  # noqa: B008
        Provide[Container.conversation_application]
    ),
) -> ConversationResponse:
    """Starts a conversation for the caller."""
    conversation_id = await application.start_conversation(
        session_id,
        title=body.title,
        active_llm_provider_id=body.llm_provider_id,
    )
    row = await application.created_conversation_row(conversation_id)
    return ConversationResponse.from_row(row)


@router.get("/conversations/{conversation_id}", response_model=ConversationResponse)
@inject
async def get_conversation(
    conversation_id: UUID,
    session_id: UUID = Depends(get_session_id),  # noqa: B008
    application: ConversationApplication = Depends(  # noqa: B008
        Provide[Container.conversation_application]
    ),
) -> ConversationResponse:
    """Returns one conversation of the caller."""
    row = await application.get_conversation(session_id, conversation_id)
    return ConversationResponse.from_row(row)


@router.patch("/conversations/{conversation_id}", response_model=OkResponse)
@inject
async def change_conversation(
    conversation_id: UUID,
    body: ConversationPatch,
    session_id: UUID = Depends(get_session_id),  # noqa: B008
    application: ConversationApplication = Depends(  # noqa: B008
        Provide[Container.conversation_application]
    ),
) -> OkResponse:
    """Changes the title or the selected provider of a conversation."""
    if body.title is not None:
        await application.rename_conversation(session_id, conversation_id, body.title)
    if body.llm_provider_id is not None:
        await application.switch_llm_provider(
            session_id,
            conversation_id,
            body.llm_provider_id,
        )
    return OkResponse()


@router.delete("/conversations/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
@inject
async def discard_conversation(
    conversation_id: UUID,
    session_id: UUID = Depends(get_session_id),  # noqa: B008
    application: ConversationApplication = Depends(  # noqa: B008
        Provide[Container.conversation_application]
    ),
) -> Response:
    """Discards a conversation."""
    await application.discard_conversation(session_id, conversation_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/conversations/{conversation_id}/messages",
    response_model=list[MessageResponse],
)
@inject
async def list_messages(
    conversation_id: UUID,
    limit: int | None = None,
    offset: int = 0,
    session_id: UUID = Depends(get_session_id),  # noqa: B008
    application: ConversationApplication = Depends(  # noqa: B008
        Provide[Container.conversation_application]
    ),
) -> list[MessageResponse]:
    """Returns the messages of a conversation, oldest first."""
    rows = await application.list_messages(
        session_id,
        conversation_id,
        limit=limit,
        offset=offset,
    )
    return [MessageResponse.from_row(row) for row in rows]


@router.get(
    "/conversations/{conversation_id}/approvals",
    response_model=list[ApprovalResponse],
)
@inject
async def list_pending_approvals(
    conversation_id: UUID,
    session_id: UUID = Depends(get_session_id),  # noqa: B008
    conversation: ConversationApplication = Depends(  # noqa: B008
        Provide[Container.conversation_application]
    ),
) -> list[ApprovalResponse]:
    """Returns the approvals of a conversation that still wait for a decision.

    A paused run blocks new messages, so a client that reloaded the page needs
    the cards back without replaying the stream.
    """
    rows = await conversation.list_pending_approvals(session_id, conversation_id)
    return [ApprovalResponse.from_row(row) for row in rows]


@router.get("/runs/{run_id}", response_model=RunResponse)
@inject
async def get_run(
    run_id: UUID,
    session_id: UUID = Depends(get_session_id),  # noqa: B008
    application: ConversationApplication = Depends(  # noqa: B008
        Provide[Container.conversation_application]
    ),
) -> RunResponse:
    """Returns one run with its approvals."""
    row = await application.get_run(session_id, run_id)
    return RunResponse.from_row(row)


# -- runs -------------------------------------------------------------------


def _stream_response(stream: RunStream, task: asyncio.Task[AgentRun]) -> StreamingResponse:
    """Wraps a run's event stream in an SSE response."""

    async def frames() -> AsyncIterator[str]:
        try:
            async for frame in stream.events():
                yield frame
        finally:
            if not task.done():
                task.cancel()

    return StreamingResponse(
        frames(),
        media_type=SSE_MEDIA_TYPE,
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _stream_run(
    factory: AgentFactory,
    request: RunRequest,
    session_id: UUID,
    raw_token: str,
) -> StreamingResponse:
    """Creates the runner, starts its task and wraps the event stream."""
    runner = factory.for_caller(
        headers={"Authorization": f"Bearer {raw_token}"},
        session_id=session_id,
    )
    run_id = uuid4()
    message_id = uuid4()
    stream = RunStream(run_id, message_id)

    async def execute() -> AgentRun:
        try:
            return await runner.run(
                request,
                observer=stream,
                run_id=run_id,
                message_id=message_id,
            )
        except Exception as exc:
            await stream.failed(run_id=run_id, error=str(exc))
            raise

    task = asyncio.create_task(execute())
    return _stream_response(stream, task)


@router.post("/conversations/{conversation_id}/messages:stream")
@inject
async def stream_message(
    conversation_id: UUID,
    body: MessageCreate,
    session_id: UUID = Depends(get_session_id),  # noqa: B008
    raw_token: str = Depends(get_bearer_token),
    conversation: ConversationApplication = Depends(  # noqa: B008
        Provide[Container.conversation_application]
    ),
    factory: AgentFactory = Depends(Provide[Container.agent_factory]),  # noqa: B008
) -> StreamingResponse:
    """Starts a run and streams its events as server-sent events."""
    row = await conversation.get_conversation(session_id, conversation_id)
    request = RunRequest(
        conversation_id=conversation_id,
        session_id=session_id,
        user_id=row.user_id,
        tenant_id=row.tenant_id,
        content=body.content,
        provider_id=body.llm_provider_id or row.active_llm_provider_id,
        auto_approve=body.auto_approve,
        page_context=body.page_context,
    )
    return _stream_run(factory, request, session_id, raw_token)


@router.post("/conversations/{conversation_id}/messages/{message_id}/edit:stream")
@inject
async def edit_message_stream(
    conversation_id: UUID,
    message_id: UUID,
    body: MessageCreate,
    session_id: UUID = Depends(get_session_id),  # noqa: B008
    raw_token: str = Depends(get_bearer_token),
    conversation: ConversationApplication = Depends(  # noqa: B008
        Provide[Container.conversation_application]
    ),
    factory: AgentFactory = Depends(Provide[Container.agent_factory]),  # noqa: B008
) -> StreamingResponse:
    """Rewrites a user message, drops its successors and regenerates the answer."""
    row = await conversation.get_conversation(session_id, conversation_id)
    history = await conversation.edit_user_message(
        session_id,
        conversation_id,
        message_id,
        body.content,
    )
    request = RunRequest(
        conversation_id=conversation_id,
        session_id=session_id,
        user_id=row.user_id,
        tenant_id=row.tenant_id,
        content=body.content,
        provider_id=body.llm_provider_id or row.active_llm_provider_id,
        auto_approve=body.auto_approve,
        page_context=body.page_context,
        history=history,
    )
    return _stream_run(factory, request, session_id, raw_token)


@router.post("/conversations/{conversation_id}/messages", response_model=RunResultResponse)
@inject
async def send_message(
    conversation_id: UUID,
    body: MessageCreate,
    session_id: UUID = Depends(get_session_id),  # noqa: B008
    raw_token: str = Depends(get_bearer_token),
    conversation: ConversationApplication = Depends(  # noqa: B008
        Provide[Container.conversation_application]
    ),
    factory: AgentFactory = Depends(Provide[Container.agent_factory]),  # noqa: B008
) -> RunResultResponse:
    """Runs the agent without streaming and returns the final result."""
    row = await conversation.get_conversation(session_id, conversation_id)
    request = RunRequest(
        conversation_id=conversation_id,
        session_id=session_id,
        user_id=row.user_id,
        tenant_id=row.tenant_id,
        content=body.content,
        provider_id=body.llm_provider_id or row.active_llm_provider_id,
        auto_approve=body.auto_approve,
        page_context=body.page_context,
    )
    runner = factory.for_caller(
        headers={"Authorization": f"Bearer {raw_token}"},
        session_id=session_id,
    )
    run = await runner.run(request)
    return _result(run)


@router.post("/runs/{run_id}/approvals/{approval_id}:stream")
@inject
async def decide_approval_stream(
    run_id: UUID,
    approval_id: UUID,
    body: ApprovalDecisionBody,
    session_id: UUID = Depends(get_session_id),  # noqa: B008
    raw_token: str = Depends(get_bearer_token),
    conversation: ConversationApplication = Depends(  # noqa: B008
        Provide[Container.conversation_application]
    ),
    factory: AgentFactory = Depends(Provide[Container.agent_factory]),  # noqa: B008
) -> StreamingResponse:
    """Records the decision and streams the rest of the paused run."""
    row = await conversation.get_run(session_id, run_id)
    if row.status != "running":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"run {run_id} is {row.status}",
        )
    conversation_row = await conversation.get_conversation(session_id, row.conversation_id)
    request = RunRequest(
        conversation_id=row.conversation_id,
        session_id=session_id,
        user_id=conversation_row.user_id,
        tenant_id=conversation_row.tenant_id,
        content="",
        provider_id=conversation_row.active_llm_provider_id,
    )
    runner = factory.for_caller(
        headers={"Authorization": f"Bearer {raw_token}"},
        session_id=session_id,
    )
    stream = RunStream(run_id, row.message_id)

    async def execute() -> AgentRun:
        try:
            return await runner.resume(
                request,
                run_id=run_id,
                message_id=row.message_id,
                approval_id=approval_id,
                approved=body.approved,
                observer=stream,
            )
        except Exception as exc:
            await stream.failed(run_id=run_id, error=str(exc))
            raise

    task = asyncio.create_task(execute())
    return _stream_response(stream, task)


def _result(run: AgentRun) -> RunResultResponse:
    """Converts a run into the non-streaming response."""
    return RunResultResponse(
        run_id=run.run_id,
        conversation_id=run.conversation_id,
        message_id=run.message_id,
        status=run.status,
        final_answer=run.final_answer,
        tools_called=len(run.tool_calls),
        resources_accessed=len(run.resources_accessed),
        input_tokens=run.usage.input_tokens,
        output_tokens=run.usage.output_tokens,
        error=run.error,
    )
