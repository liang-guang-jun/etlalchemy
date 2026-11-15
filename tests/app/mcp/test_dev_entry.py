"""Tests for the standalone MCP entry point used by development tools."""

import asyncio
import time
from pathlib import Path
from typing import Any

from fastmcp import Client, FastMCP
from fastmcp.utilities.mcp_server_config.v1.sources.filesystem import FileSystemSource

DEV_ENTRY = "etlalchemy/app/mcp/dev.py:create_mcp_server"
WAIT_TIMEOUT = 10.0


async def load_server() -> FastMCP:
    """Loads the server the same way `fastmcp dev inspector` does."""

    async def run() -> FastMCP:
        source = FileSystemSource(path=DEV_ENTRY)
        server = await source.load_server()
        assert isinstance(server, FastMCP)
        return server

    return await run()


async def test_dev_entry_point_is_loadable(config_dir: Path) -> None:
    """The inspector can resolve the factory and list every primitive."""
    server = await load_server()

    async def names() -> tuple[set[str], set[str]]:
        async with Client(server) as client:
            tools = {tool.name for tool in await client.list_tools()}
            prompts = {prompt.name for prompt in await client.list_prompts()}
        return tools, prompts

    tools, prompts = await names()

    assert len(tools) == 108
    assert len(prompts) == 15


async def test_dev_entry_point_starts_the_container(config_dir: Path) -> None:
    """The dev lifespan initialises the container, so tools and resources work."""
    server = await load_server()

    async def exercise() -> tuple[dict[str, Any], str]:
        async with Client(server) as client:
            created = await client.call_tool("create_catalog", {"name": "analytics"})
            catalog_id = created.structured_content["catalog_id"]
            deadline = time.monotonic() + WAIT_TIMEOUT
            text = "[]"
            while time.monotonic() < deadline:
                contents = await client.read_resource("catalog:///all")
                text = contents[0].text
                if catalog_id in text:
                    break
                await asyncio.sleep(0.05)
            return created.structured_content, text

    created, text = await exercise()

    assert "catalog_id" in created
    assert created["catalog_id"] in text
