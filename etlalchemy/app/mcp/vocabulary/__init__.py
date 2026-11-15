"""Vocabulary context MCP primitives: tools, resources and prompts."""

from __future__ import annotations

from fastmcp import FastMCP

from etlalchemy.app.bootstrap import Container
from etlalchemy.app.mcp.registry import mcp_context
from etlalchemy.app.mcp.vocabulary import prompts, resources, tools

INSTRUCTIONS = (
    "Read the vocabulary with the vocabulary:/// resources; change it with the "
    "vocabulary tools. Terms form a tree addressed by full path or id, and a term "
    "is a draft until it is approved. Each term may carry a #rrggbb colour that "
    "only decorates it in the UI."
)
"""Description of the vocabulary context."""

__all__ = ["INSTRUCTIONS", "prompts", "register", "resources", "tools"]


@mcp_context("vocabulary", INSTRUCTIONS)
def register(mcp: FastMCP, container: Container) -> None:
    """Registers the vocabulary tools, resources and prompts on the given server."""
    tools.register(mcp, container)
    resources.register(mcp, container)
    prompts.register(mcp)
