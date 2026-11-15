"""Read-only conversation tools.

Both tools resolve the caller through the MCP session resolver, so a caller only
ever sees its own conversations.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastmcp import FastMCP
from pydantic import Field

from etlalchemy.app.bootstrap import Container
from etlalchemy.app.mcp.errors import mcp_error_guard
from etlalchemy.app.schemas.agent import ConversationResponse, MessageResponse


def register(mcp: FastMCP, container: Container) -> None:
    """Registers the conversation tools on the given server."""

    @mcp.tool(
        name="list_conversations",
        description="List the conversations of the caller, most recently active first.",
        annotations={"readOnlyHint": True},
    )
    async def list_conversations(
        limit: Annotated[
            int | None,
            Field(description="Maximum number of conversations to return."),
        ] = None,
        offset: Annotated[int, Field(description="Number of conversations to skip.")] = 0,
    ) -> list[ConversationResponse]:
        """List the conversations of the caller."""
        session_id = container.mcp_session_resolver()
        with mcp_error_guard():
            rows = await container.conversation_application().list_conversations(
                session_id,
                limit=limit,
                offset=offset,
            )
        return [ConversationResponse.from_row(row) for row in rows]

    @mcp.tool(
        name="list_conversation_messages",
        description="List the messages of one conversation of the caller, oldest first.",
        annotations={"readOnlyHint": True},
    )
    async def list_conversation_messages(
        conversation_id: Annotated[UUID, Field(description="ID of the conversation.")],
        limit: Annotated[
            int | None,
            Field(description="Maximum number of messages to return."),
        ] = None,
        offset: Annotated[int, Field(description="Number of messages to skip.")] = 0,
    ) -> list[MessageResponse]:
        """List the messages of one conversation."""
        session_id = container.mcp_session_resolver()
        with mcp_error_guard():
            rows = await container.conversation_application().list_messages(
                session_id,
                conversation_id,
                limit=limit,
                offset=offset,
            )
        return [MessageResponse.from_row(row) for row in rows]
