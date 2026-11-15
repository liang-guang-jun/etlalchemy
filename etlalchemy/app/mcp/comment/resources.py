"""Comment context MCP resources.

Every resource answers ``application/json`` text and returns ``null`` or ``[]``
instead of raising when the thread or id is unknown.
"""

from __future__ import annotations

from fastmcp import FastMCP

from etlalchemy.app.bootstrap import Container
from etlalchemy.app.schemas.comment import CommentResponse, ThreadResponse
from etlalchemy.shared.utils import dump, uuid_or_none


def register(mcp: FastMCP, container: Container) -> None:
    """Registers the comment resources on the given server."""

    @mcp.resource(
        "comment:///threads/{thread_id}",
        name="thread",
        description="One live thread with its comments, or null when it does not exist.",
        mime_type="application/json",
    )
    async def thread(thread_id: str) -> str:
        """Return one thread with its comments."""
        key = uuid_or_none(thread_id)
        row = None if key is None else await container.comment_view().get_thread(key)
        if row is None or key is None:
            return dump(None)
        comments = await container.comment_view().list_comments(key)
        return dump(
            {
                "thread": ThreadResponse.from_row(row).model_dump(mode="json"),
                "comments": [
                    CommentResponse.from_row(comment).model_dump(mode="json")
                    for comment in comments
                ],
            },
        )

    @mcp.resource(
        "comment:///threads/{thread_id}/comments",
        name="thread-comments",
        description="The live comments of a thread in creation order.",
        mime_type="application/json",
    )
    async def thread_comments(thread_id: str) -> str:
        """Return the comments of a thread."""
        key = uuid_or_none(thread_id)
        if key is None:
            return dump([])
        rows = [
            CommentResponse.from_row(row)
            for row in await container.comment_view().list_comments(key)
        ]
        return dump([row.model_dump(mode="json") for row in rows])

    @mcp.resource(
        "comment:///targets/{target_type}/{target_id}/threads",
        name="target-threads",
        description="The live threads attached to one target, most recently active first.",
        mime_type="application/json",
    )
    async def target_threads(target_type: str, target_id: str) -> str:
        """Return the threads of one target."""
        key = uuid_or_none(target_id)
        if key is None:
            return dump([])
        rows = [
            ThreadResponse.from_row(row)
            for row in await container.comment_view().list_threads_for_target(
                target_type,
                key,
            )
        ]
        return dump([row.model_dump(mode="json") for row in rows])
