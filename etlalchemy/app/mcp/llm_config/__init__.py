"""LLM provider context MCP primitives: one read-only tool and two resources."""

from __future__ import annotations

from fastmcp import FastMCP

from etlalchemy.app.bootstrap import Container
from etlalchemy.app.mcp.llm_config import resources as resources
from etlalchemy.app.mcp.llm_config import tools as tools
from etlalchemy.app.mcp.registry import mcp_context

INSTRUCTIONS = (
    "Read the LLM providers of the caller with the list_llm_providers tool; the "
    "llm_config:/// resources expose the public providers only, because a resource "
    "carries no caller identity. Providers are created and changed over HTTP at "
    "/agent/llm-providers, never from a tool."
)
"""Description of the LLM provider context."""

__all__ = ["INSTRUCTIONS", "register", "resources", "tools"]


@mcp_context("llm_config", INSTRUCTIONS)
def register(mcp: FastMCP, container: Container) -> None:
    """Registers the LLM provider primitives on the given server."""
    tools.register(mcp, container)
    resources.register(mcp, container)
