"""Standalone MCP entry point for development tools such as the MCP Inspector.

The HTTP application starts the container in its FastAPI lifespan. A server that
runs on its own (stdio transport) needs a lifespan of its own, which is what this
factory adds:

    fastmcp dev inspector etlalchemy/app/mcp/dev.py:create_mcp_server
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from dependency_injector import providers
from fastmcp import FastMCP

from etlalchemy.app.bootstrap import Container, run_container
from etlalchemy.app.mcp.server import MCPServer


def create_mcp_server() -> FastMCP:
    """Builds the MCP server with a container that starts with the session."""
    container = Container()

    @asynccontextmanager
    async def lifespan(server: FastMCP) -> AsyncIterator[None]:
        """Wires the container and runs its resources for the MCP session."""
        async with run_container(container):
            yield

    server = MCPServer(container, lifespan=lifespan)
    # Same invariant as ``create_app``: the container exposes the one server of
    # this process, so a run started here also calls it in-process.
    container.mcp_server.override(providers.Object(server))
    return server.mcp
