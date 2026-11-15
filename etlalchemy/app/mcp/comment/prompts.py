"""English workflow prompts for the comment context."""

from __future__ import annotations

from typing import Annotated

from fastmcp import FastMCP
from pydantic import Field


def register(mcp: FastMCP) -> None:
    """Registers the comment prompts on the given server."""

    @mcp.prompt(
        name="review-thread",
        description="Summarize a comment thread and list the questions still open.",
    )
    def review_thread(
        thread_id: Annotated[str, Field(description="ID of the thread to review.")],
    ) -> str:
        """Return the thread review template."""
        return f"""
Review the thread at `comment:///threads/{thread_id}`.

1. Read the thread and its comments; the `depth` field shows the reply nesting.
2. Summarize the original request and the decisions taken so far.
3. List every question that still has no answer, with the users involved.
4. Do not resolve or discard anything: report the findings and let the user decide.
"""

    @mcp.prompt(
        name="resolve-discussion",
        description="Decide whether a discussion can be resolved.",
    )
    def resolve_discussion(
        thread_id: Annotated[str, Field(description="ID of the thread to assess.")],
    ) -> str:
        """Return the resolution-assessment template."""
        return f"""
Assess whether the discussion at `comment:///threads/{thread_id}` is settled.

1. Read the thread and its live comments.
2. Check that every question has an answer and that the participants agree.
3. If it is settled, tell the user and ask for explicit consent before calling
   `resolve_thread`. Otherwise list what is missing.
4. Never resolve the thread on your own.
"""

    @mcp.prompt(
        name="draft-reply",
        description="Draft a reply to a comment thread.",
    )
    def draft_reply(
        thread_id: Annotated[str, Field(description="ID of the thread to reply to.")],
        intent: Annotated[str, Field(description="What the reply should convey.")] = "",
    ) -> str:
        """Return the reply-drafting template."""
        return f"""
Draft a reply for the thread at `comment:///threads/{thread_id}`.

1. Read the thread and the comments that are relevant to the intent.
2. Write a short plain-text reply. The user's intent is: {intent or "answer the open question"}.
3. Suggest the users to mention, using ids from `iam:///users`; do not invent ids.
4. Reply with the parent comment id when the reply belongs to a specific comment.
5. Show the draft to the user before calling `add_comment`.
"""

    @mcp.prompt(
        name="open-thread-for-target",
        description="Suggest opening a discussion thread for an element that has none.",
    )
    def open_thread_for_target(
        target_type: Annotated[str, Field(description="Type of the element.")],
        target_id: Annotated[str, Field(description="ID of the element.")],
    ) -> str:
        """Return the thread-opening template."""
        return f"""
Check whether the element `{target_type}` with id `{target_id}` needs a thread.

1. Read `comment:///targets/{target_type}/{target_id}/threads`.
2. If a live thread already exists, summarize it instead of creating another.
3. Otherwise explain why the element deserves discussion and propose a title and a
   first comment. Create the thread only after the user agrees.
"""
