"""Conversation context MCP primitives: two read-only tools."""

from __future__ import annotations

from fastmcp import FastMCP

from etlalchemy.app.bootstrap import Container
from etlalchemy.app.mcp.conversation import tools as tools
from etlalchemy.app.mcp.registry import mcp_context

INSTRUCTIONS = (
    "Read the caller's conversations with the list_conversations and "
    "list_conversation_messages tools. Conversations are created and driven over "
    "HTTP at /agent/conversations; this context exposes no resource because a "
    "conversation is always scoped to one caller."
)
"""Description of the conversation context."""

__all__ = ["INSTRUCTIONS", "register", "tools"]


@mcp_context("conversation", INSTRUCTIONS)
def register(mcp: FastMCP, container: Container) -> None:
    """Registers the conversation primitives on the given server."""
    tools.register(mcp, container)
