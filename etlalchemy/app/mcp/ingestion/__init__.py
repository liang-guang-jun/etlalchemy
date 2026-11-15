"""Ingestion context MCP primitives: tools, resources and prompts."""

from __future__ import annotations

from fastmcp import FastMCP

from etlalchemy.app.bootstrap import Container
from etlalchemy.app.mcp.ingestion import prompts, resources, tools
from etlalchemy.app.mcp.registry import mcp_context

INSTRUCTIONS = (
    "Read ingestion with the ingestion:/// resources; run imports with the ingestion tools."
)
"""Description of the ingestion context."""


@mcp_context("ingestion", INSTRUCTIONS)
def register(mcp: FastMCP, container: Container) -> None:
    """Registers the ingestion tools, resources and prompts on the given server."""
    tools.register(mcp, container)
    resources.register(mcp, container)
    prompts.register(mcp)
