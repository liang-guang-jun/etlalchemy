"""Catalog context MCP primitives: tools, resources and prompts."""

from __future__ import annotations

from fastmcp import FastMCP

from etlalchemy.app.bootstrap import Container
from etlalchemy.app.mcp.catalog import prompts, resources, tools
from etlalchemy.app.mcp.registry import mcp_context

INSTRUCTIONS = "Read the catalog with the catalog:/// resources; change it with the catalog tools."
"""Description of the catalog context."""


@mcp_context("catalog", INSTRUCTIONS)
def register(mcp: FastMCP, container: Container) -> None:
    """Registers the catalog tools, resources and prompts on the given server."""
    tools.register(mcp, container)
    resources.register(mcp, container)
    prompts.register(mcp)
