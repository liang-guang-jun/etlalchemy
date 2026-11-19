"""HTTP routes exposing the comment context."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from dependency_injector.wiring import Provide, inject
from eventsourcing.application import AggregateNotFoundError
from eventsourcing.persistence import RecordConflictError
from fastapi import APIRouter, Depends, FastAPI, Query
from pydantic import BaseModel, Field

from etlalchemy.app.api.dependencies.auth import get_session_id
from etlalchemy.app.api.errors import install_exception_handlers
from etlalchemy.app.bootstrap import Container
from etlalchemy.app.schemas.comment import (
    CommentCreatedResponse,
    CommentResponse,
    TargetLookup,
    TargetResponse,
    ThreadCreatedResponse,
    ThreadDetailResponse,
    ThreadResponse,
)
from etlalchemy.app.schemas.common import OkResponse
from etlalchemy.comment.aggregates.errors import (
    CommentBodyEmptyError,
    CommentBodyTooLongError,
    CommentError,
    CommentValidationError,
    InvalidThreadTransitionError,
    MentionsLimitExceededError,
    UnknownCommentError,
    UnknownMentionedUserError,
    UnknownTargetError,
    UnknownTargetTypeError,
    UnknownThreadError,
)
from etlalchemy.comment.application import CommentApplication
from etlalchemy.comment.ports.target_lookup import TargetLookupPort
from etlalchemy.iam.aggregates.errors import (
    AuthenticationError,
    PermissionDeniedError,
    SessionExpiredError,
    SessionRevokedError,
)

router = APIRouter(prefix="/comments", tags=["comments"])

CONFLICT_ERRORS = (CommentError, RecordConflictError)
NOT_FOUND_ERRORS = (
    UnknownThreadError,
    UnknownCommentError,
    UnknownTargetTypeError,
    UnknownTargetError,
    UnknownMentionedUserError,
    AggregateNotFoundError,
)
BAD_REQUEST_ERRORS = (
    CommentBodyEmptyError,
    CommentBodyTooLongError,
    CommentValidationError,
    MentionsLimitExceededError,
    InvalidThreadTransitionError,
)
UNAUTHORIZED_ERRORS = (
    AuthenticationError,
    SessionExpiredError,
    SessionRevokedError,
)
FORBIDDEN_ERRORS = (PermissionDeniedError,)


def add_exception_handlers(app: FastAPI) -> None:
    """Maps comment and IAM errors to HTTP responses."""
    install_exception_handlers(
        app,
        conflict=CONFLICT_ERRORS,
        not_found=NOT_FOUND_ERRORS,
        bad_request=(*BAD_REQUEST_ERRORS, ValueError),
        unauthorized=UNAUTHORIZED_ERRORS,
        forbidden=FORBIDDEN_ERRORS,
    )


class ThreadCreate(BaseModel):
    """Body of ``POST /comments/threads``."""

    target_type: str
    """Type of the commented element."""
    target_id: UUID
    """ID of the commented element."""
    body: str
    """Body of the first comment."""
    title: str = ""
    """Optional thread title."""
    mentions: list[UUID] = Field(default_factory=list)
    """Users mentioned by the first comment."""


class CommentCreate(BaseModel):
    """Body of ``POST /comments/threads/{thread_id}/comments``."""

    body: str
    """Body of the comment."""
    parent_comment_id: UUID | None = None
    """Comment this one replies to, or ``None`` for a new root comment."""
    mentions: list[UUID] = Field(default_factory=list)
    """Users mentioned by the comment."""


class CommentEdit(BaseModel):
    """Body of ``PATCH /comments/threads/{thread_id}/comments/{comment_id}``."""

    body: str | None = None
    """New body, or ``None`` to keep the current one."""
    mentions: list[UUID] | None = None
    """New mentions, or ``None`` to keep the current ones."""


@router.get("/targets/{target_type}/{target_id}", response_model=TargetResponse)
@inject
async def describe_target(
    target_type: str,
    target_id: UUID,
    lookup: TargetLookupPort = Depends(  # noqa: B008
        Provide[Container.comment_target_lookup]
    ),
) -> TargetResponse:
    """Returns what one target is called, so a client can render a link."""
    description = await lookup.describe(target_type, target_id)
    if description is None:
        msg = f"{target_type} {target_id} does not exist"
        raise UnknownTargetError(msg)
    return TargetResponse.from_description(description)


@router.post("/targets/lookup", response_model=list[TargetResponse])
@inject
async def describe_targets(
    body: TargetLookup,
    lookup: TargetLookupPort = Depends(  # noqa: B008
        Provide[Container.comment_target_lookup]
    ),
) -> list[TargetResponse]:
    """Describes several targets at once; unknown ones are left out."""
    seen: set[tuple[str, UUID]] = set()
    described: list[TargetResponse] = []
    for ref in body.refs:
        key = (ref.target_type, ref.target_id)
        if key in seen:
            continue
        seen.add(key)
        description = await lookup.describe(ref.target_type, ref.target_id)
        if description is not None:
            described.append(TargetResponse.from_description(description))
    return described


@router.post("/threads", status_code=201, response_model=ThreadCreatedResponse)
@inject
async def create_thread(
    body: ThreadCreate,
    session_id: UUID = Depends(get_session_id),  # noqa: B008
    application: CommentApplication = Depends(  # noqa: B008
        Provide[Container.comment_application]
    ),
) -> ThreadCreatedResponse:
    """Starts a thread and returns the new thread and root comment ids."""
    created = await application.create_thread(
        session_id,
        body.target_type,
        body.target_id,
        body.body,
        body.mentions or None,
        body.title,
    )
    return ThreadCreatedResponse(
        thread_id=created.thread_id,
        root_comment_id=created.root_comment_id,
    )


@router.get("/threads", response_model=list[ThreadResponse])
@inject
async def list_threads(
    session_id: UUID = Depends(get_session_id),  # noqa: B008
    target_type: Annotated[str | None, Query()] = None,
    target_id: Annotated[UUID | None, Query()] = None,
    author_user_id: Annotated[UUID | None, Query()] = None,
    mention_user_id: Annotated[UUID | None, Query()] = None,
    status: Annotated[str | None, Query()] = None,
    limit: Annotated[int | None, Query(ge=1)] = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    application: CommentApplication = Depends(  # noqa: B008
        Provide[Container.comment_application]
    ),
) -> list[ThreadResponse]:
    """Lists live threads, filtered by the given criteria."""
    rows = await application.list_threads(
        session_id,
        target_type,
        target_id,
        author_user_id,
        mention_user_id,
        status,
        limit,
        offset,
    )
    return [ThreadResponse.from_row(row) for row in rows]


@router.get("/threads/{thread_id}", response_model=ThreadDetailResponse)
@inject
async def get_thread(
    thread_id: UUID,
    session_id: UUID = Depends(get_session_id),  # noqa: B008
    application: CommentApplication = Depends(  # noqa: B008
        Provide[Container.comment_application]
    ),
) -> ThreadDetailResponse:
    """Returns a thread with its comments."""
    detail = await application.get_thread(thread_id, session_id)
    return ThreadDetailResponse(
        thread=ThreadResponse.from_row(detail.thread),
        comments=[CommentResponse.from_row(row) for row in detail.comments],
    )


@router.get("/threads/{thread_id}/comments", response_model=list[CommentResponse])
@inject
async def list_comments(
    thread_id: UUID,
    session_id: UUID = Depends(get_session_id),  # noqa: B008
    limit: Annotated[int | None, Query(ge=1)] = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    flatten_after: Annotated[int | None, Query(ge=0)] = None,
    include_discarded: Annotated[bool, Query()] = False,
    application: CommentApplication = Depends(  # noqa: B008
        Provide[Container.comment_application]
    ),
) -> list[CommentResponse]:
    """Lists the comments of a thread, optionally capping their depth."""
    rows = await application.list_comments(
        thread_id,
        session_id,
        limit,
        offset,
        flatten_after,
        include_discarded,
    )
    return [CommentResponse.from_row(row) for row in rows]


@router.post(
    "/threads/{thread_id}/comments",
    status_code=201,
    response_model=CommentCreatedResponse,
)
@inject
async def add_comment(
    thread_id: UUID,
    body: CommentCreate,
    session_id: UUID = Depends(get_session_id),  # noqa: B008
    application: CommentApplication = Depends(  # noqa: B008
        Provide[Container.comment_application]
    ),
) -> CommentCreatedResponse:
    """Adds a comment or a reply and reports its depth."""
    created = await application.add_comment(
        session_id,
        thread_id,
        body.body,
        body.parent_comment_id,
        body.mentions or None,
    )
    return CommentCreatedResponse(
        comment_id=created.comment_id,
        depth=created.depth,
        depth_warning=created.depth_warning,
    )


@router.patch(
    "/threads/{thread_id}/comments/{comment_id}",
    response_model=OkResponse,
)
@inject
async def edit_comment(
    thread_id: UUID,
    comment_id: UUID,
    body: CommentEdit,
    session_id: UUID = Depends(get_session_id),  # noqa: B008
    application: CommentApplication = Depends(  # noqa: B008
        Provide[Container.comment_application]
    ),
) -> OkResponse:
    """Changes the body and/or mentions of a comment."""
    await application.edit_comment(
        session_id,
        thread_id,
        comment_id,
        body.body,
        body.mentions,
    )
    return OkResponse()


@router.delete("/threads/{thread_id}/comments/{comment_id}", status_code=204)
@inject
async def discard_comment(
    thread_id: UUID,
    comment_id: UUID,
    session_id: UUID = Depends(get_session_id),  # noqa: B008
    application: CommentApplication = Depends(  # noqa: B008
        Provide[Container.comment_application]
    ),
) -> None:
    """Soft-deletes a comment."""
    await application.discard_comment(session_id, thread_id, comment_id)


@router.post("/threads/{thread_id}/resolve", response_model=OkResponse)
@inject
async def resolve_thread(
    thread_id: UUID,
    session_id: UUID = Depends(get_session_id),  # noqa: B008
    application: CommentApplication = Depends(  # noqa: B008
        Provide[Container.comment_application]
    ),
) -> OkResponse:
    """Marks a thread as resolved."""
    await application.resolve_thread(session_id, thread_id)
    return OkResponse()


@router.post("/threads/{thread_id}/reopen", response_model=OkResponse)
@inject
async def reopen_thread(
    thread_id: UUID,
    session_id: UUID = Depends(get_session_id),  # noqa: B008
    application: CommentApplication = Depends(  # noqa: B008
        Provide[Container.comment_application]
    ),
) -> OkResponse:
    """Reopens a resolved thread."""
    await application.reopen_thread(session_id, thread_id)
    return OkResponse()


@router.delete("/threads/{thread_id}", status_code=204)
@inject
async def discard_thread(
    thread_id: UUID,
    session_id: UUID = Depends(get_session_id),  # noqa: B008
    application: CommentApplication = Depends(  # noqa: B008
        Provide[Container.comment_application]
    ),
) -> None:
    """Soft-deletes a thread."""
    await application.discard_thread(session_id, thread_id)
