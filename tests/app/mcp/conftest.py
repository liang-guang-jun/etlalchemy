"""Shared fixtures for the MCP delivery tests."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from etlalchemy.app.bootstrap import Container, run_container
from etlalchemy.app.mcp.server import MCPServer


@pytest.fixture
async def container(config_dir: Path) -> AsyncIterator[Container]:
    """Returns a container whose read models and resources are running."""
    container = Container()
    async with run_container(container):
        yield container


@pytest.fixture
async def server(container: Container) -> MCPServer:
    """Returns an MCP server bound to the fixture container."""
    return MCPServer(container)
