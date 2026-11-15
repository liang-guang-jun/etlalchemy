"""Comment context MCP primitives: tools, resources and prompts."""

from __future__ import annotations

from fastmcp import FastMCP

from etlalchemy.app.bootstrap import Container
from etlalchemy.app.mcp.comment import prompts, resources, tools
from etlalchemy.app.mcp.registry import mcp_context

INSTRUCTIONS = (
    "Read threads with the comment:/// resources; write with the comment tools. "
    "A thread accepts comments only while it is OPEN. Never resolve or discard a "
    "thread, and never discard a comment, without explicit user consent."
)
"""Description of the comment context."""

__all__ = ["INSTRUCTIONS", "prompts", "register", "resources", "tools"]


@mcp_context("comment", INSTRUCTIONS)
def register(mcp: FastMCP, container: Container) -> None:
    """Registers the comment tools, resources and prompts on the given server."""
    tools.register(mcp, container)
    resources.register(mcp, container)
    prompts.register(mcp)
