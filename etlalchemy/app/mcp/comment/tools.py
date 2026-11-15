"""Comment context MCP tools."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastmcp import FastMCP
from pydantic import Field

from etlalchemy.app.bootstrap import Container
from etlalchemy.app.mcp.errors import mcp_error_guard
from etlalchemy.app.schemas.comment import (
    CommentCreatedResponse,
    CommentResponse,
    ThreadCreatedResponse,
    ThreadDetailResponse,
    ThreadResponse,
)
from etlalchemy.app.schemas.common import OkResponse

MENTIONS_HINT = (
    "User ids to mention. Only users visible through the iam:///users resources "
    "are accepted; an unknown or inactive user is rejected."
)
"""Description shared by the mention arguments."""


def register(mcp: FastMCP, container: Container) -> None:
    """Registers the comment tools on the given server."""
    # ---- write -----------------------------------------------------------

    @mcp.tool(
        name="create_thread",
        description=(
            "Start a comment thread with its first comment and return the thread id "
            "and the root comment id."
        ),
    )
    async def create_thread(
        target_type: Annotated[
            str,
            Field(description="Type of the commented element, for example table."),
        ],
        target_id: Annotated[UUID, Field(description="ID of the commented element.")],
        body: Annotated[str, Field(description="Body of the first comment.")],
        title: Annotated[str, Field(description="Optional thread title.")] = "",
        mentions: Annotated[
            list[UUID] | None,
            Field(description=MENTIONS_HINT),
        ] = None,
    ) -> ThreadCreatedResponse:
        """Create a thread."""
        session_id = container.mcp_session_resolver()
        with mcp_error_guard():
            created = await container.comment_application().create_thread(
                session_id,
                target_type,
                target_id,
                body,
                mentions,
                title,
            )
        return ThreadCreatedResponse(
            thread_id=created.thread_id,
            root_comment_id=created.root_comment_id,
        )

    @mcp.tool(
        name="add_comment",
        description=(
            "Add a comment or a reply and return its depth. A depth_warning is only "
            "advice: the comment is saved. When you receive one, tell the user that a "
            "new thread may be a better place to continue."
        ),
    )
    async def add_comment(
        thread_id: Annotated[UUID, Field(description="ID of the thread.")],
        body: Annotated[str, Field(description="Body of the comment.")],
        parent_comment_id: Annotated[
            UUID | None,
            Field(description="Comment to reply to, or null for a new root comment."),
        ] = None,
        mentions: Annotated[
            list[UUID] | None,
            Field(description=MENTIONS_HINT),
        ] = None,
    ) -> CommentCreatedResponse:
        """Add a comment."""
        session_id = container.mcp_session_resolver()
        with mcp_error_guard():
            created = await container.comment_application().add_comment(
                session_id,
                thread_id,
                body,
                parent_comment_id,
                mentions,
            )
        return CommentCreatedResponse(
            comment_id=created.comment_id,
            depth=created.depth,
            depth_warning=created.depth_warning,
        )

    @mcp.tool(
        name="edit_comment",
        description="Change the body and/or mentions of your own comment.",
    )
    async def edit_comment(
        thread_id: Annotated[UUID, Field(description="ID of the thread.")],
        comment_id: Annotated[UUID, Field(description="ID of the comment to edit.")],
        body: Annotated[
            str | None,
            Field(description="New body, or null to keep the current one."),
        ] = None,
        mentions: Annotated[
            list[UUID] | None,
            Field(description="New mentions, or null to keep the current ones."),
        ] = None,
    ) -> OkResponse:
        """Edit a comment."""
        session_id = container.mcp_session_resolver()
        with mcp_error_guard():
            await container.comment_application().edit_comment(
                session_id,
                thread_id,
                comment_id,
                body,
                mentions,
            )
        return OkResponse()

    @mcp.tool(
        name="discard_comment",
        description="Soft-delete a comment. Ask the user for explicit consent first.",
        annotations={"destructiveHint": True},
    )
    async def discard_comment(
        thread_id: Annotated[UUID, Field(description="ID of the thread.")],
        comment_id: Annotated[UUID, Field(description="ID of the comment to discard.")],
    ) -> OkResponse:
        """Discard a comment."""
        session_id = container.mcp_session_resolver()
        with mcp_error_guard():
            await container.comment_application().discard_comment(
                session_id,
                thread_id,
                comment_id,
            )
        return OkResponse()

    @mcp.tool(
        name="resolve_thread",
        description=(
            "Mark a thread as resolved. Do not resolve without the user's explicit consent."
        ),
    )
    async def resolve_thread(
        thread_id: Annotated[UUID, Field(description="ID of the thread to resolve.")],
    ) -> OkResponse:
        """Resolve a thread."""
        session_id = container.mcp_session_resolver()
        with mcp_error_guard():
            await container.comment_application().resolve_thread(session_id, thread_id)
        return OkResponse()

    @mcp.tool(
        name="reopen_thread",
        description="Reopen a resolved thread so it accepts comments again.",
    )
    async def reopen_thread(
        thread_id: Annotated[UUID, Field(description="ID of the thread to reopen.")],
    ) -> OkResponse:
        """Reopen a thread."""
        session_id = container.mcp_session_resolver()
        with mcp_error_guard():
            await container.comment_application().reopen_thread(session_id, thread_id)
        return OkResponse()

    @mcp.tool(
        name="discard_thread",
        description=(
            "Soft-delete a thread and hide it from every read. Ask the user for "
            "explicit consent first."
        ),
        annotations={"destructiveHint": True},
    )
    async def discard_thread(
        thread_id: Annotated[UUID, Field(description="ID of the thread to discard.")],
    ) -> OkResponse:
        """Discard a thread."""
        session_id = container.mcp_session_resolver()
        with mcp_error_guard():
            await container.comment_application().discard_thread(session_id, thread_id)
        return OkResponse()

    # ---- read ------------------------------------------------------------

    @mcp.tool(
        name="list_threads",
        description=(
            "List live threads, filtered by target, author, mentioned user or status. "
            "Reads are scoped to the authenticated caller."
        ),
        annotations={"readOnlyHint": True},
    )
    async def list_threads(
        target_type: Annotated[
            str | None,
            Field(description="Only threads on this target type."),
        ] = None,
        target_id: Annotated[
            UUID | None,
            Field(description="Only threads on this target id."),
        ] = None,
        author_user_id: Annotated[
            UUID | None,
            Field(description="Only threads started by this user."),
        ] = None,
        mention_user_id: Annotated[
            UUID | None,
            Field(description="Only threads with a comment that mentions this user."),
        ] = None,
        status: Annotated[
            str | None,
            Field(
                description=(
                    "Only threads in this status. Discarded threads are never listed, "
                    "so use OPEN or RESOLVED."
                )
            ),
        ] = None,
        limit: Annotated[
            int | None,
            Field(description="Maximum number of rows to return."),
        ] = None,
        offset: Annotated[int, Field(description="Rows to skip.")] = 0,
    ) -> list[ThreadResponse]:
        """List threads."""
        session_id = container.mcp_session_resolver()
        with mcp_error_guard():
            rows = await container.comment_application().list_threads(
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

    @mcp.tool(
        name="get_thread",
        description="Return one live thread with all of its comments.",
        annotations={"readOnlyHint": True},
    )
    async def get_thread(
        thread_id: Annotated[UUID, Field(description="ID of the thread.")],
    ) -> ThreadDetailResponse:
        """Return one thread."""
        session_id = container.mcp_session_resolver()
        with mcp_error_guard():
            detail = await container.comment_application().get_thread(thread_id, session_id)
        return ThreadDetailResponse(
            thread=ThreadResponse.from_row(detail.thread),
            comments=[CommentResponse.from_row(row) for row in detail.comments],
        )

    @mcp.tool(
        name="list_comments",
        description=(
            "List the comments of a thread in creation order. Use flatten_after to "
            "cap the returned depth for a flat presentation; the parent chain is not "
            "changed."
        ),
        annotations={"readOnlyHint": True},
    )
    async def list_comments(
        thread_id: Annotated[UUID, Field(description="ID of the thread.")],
        limit: Annotated[
            int | None,
            Field(description="Maximum number of rows to return."),
        ] = None,
        offset: Annotated[int, Field(description="Rows to skip.")] = 0,
        flatten_after: Annotated[
            int | None,
            Field(description="Cap the returned depth at this value, or null for the real depth."),
        ] = None,
        include_discarded: Annotated[
            bool,
            Field(description="Include soft-deleted comments."),
        ] = False,
    ) -> list[CommentResponse]:
        """List comments."""
        session_id = container.mcp_session_resolver()
        with mcp_error_guard():
            rows = await container.comment_application().list_comments(
                thread_id,
                session_id,
                limit,
                offset,
                flatten_after,
                include_discarded,
            )
        return [CommentResponse.from_row(row) for row in rows]
