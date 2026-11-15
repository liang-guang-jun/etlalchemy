"""Semantic context MCP primitives: tools, resources and prompts."""

from __future__ import annotations

from fastmcp import FastMCP

from etlalchemy.app.bootstrap import Container
from etlalchemy.app.mcp.registry import mcp_context
from etlalchemy.app.mcp.semantic import prompts, resources, tools

INSTRUCTIONS = (
    "Read semantic models with the semantic:/// resources; change them with the "
    "semantic tools. A model always owns the 'All' diagram, which automatically "
    "shows every entity: its nodes cannot be placed or removed there, but they can "
    "be moved to lay out the overview. Removing an entity cascades to the "
    "relationships and diagram nodes that reference it."
)
"""Description of the semantic context."""

__all__ = ["INSTRUCTIONS", "prompts", "register", "resources", "tools"]


@mcp_context("semantic", INSTRUCTIONS)
def register(mcp: FastMCP, container: Container) -> None:
    """Registers the semantic tools, resources and prompts on the given server."""
    tools.register(mcp, container)
    resources.register(mcp, container)
    prompts.register(mcp)
