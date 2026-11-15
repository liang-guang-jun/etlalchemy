"""IAM context MCP primitives: read-only tools, resources and prompts."""

from __future__ import annotations

from fastmcp import FastMCP

from etlalchemy.app.bootstrap import Container
from etlalchemy.app.mcp.iam import prompts, resources, tools
from etlalchemy.app.mcp.registry import mcp_context

INSTRUCTIONS = (
    "Read identities, tenants and groups with the iam:/// resources. The IAM tools "
    "are read only on purpose: creating users, granting permissions and changing "
    "credentials stay in the CLI and the HTTP API, which carry a session."
)
"""Description of the IAM context."""

__all__ = ["INSTRUCTIONS", "prompts", "register", "resources", "tools"]


@mcp_context("iam", INSTRUCTIONS)
def register(mcp: FastMCP, container: Container) -> None:
    """Registers the IAM tools, resources and prompts on the given server."""
    tools.register(mcp, container)
    resources.register(mcp, container)
    prompts.register(mcp)
