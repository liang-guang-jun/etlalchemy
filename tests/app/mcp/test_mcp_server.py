"""Tests for the mounted sub-server structure of the MCP server."""

from __future__ import annotations

import pytest
from etlalchemy.app.mcp import registry
from etlalchemy.app.mcp import server as server_module
from etlalchemy.app.mcp.server import MCPServer
from fastmcp import Client, FastMCP


async def _surface(mcp: FastMCP) -> dict[str, set[str]]:
    """Returns the tools, resources, templates and prompts a client sees."""

    async def run() -> dict[str, set[str]]:
        async with Client(mcp) as client:
            return {
                "tools": {tool.name for tool in await client.list_tools()},
                "resources": {str(resource.uri) for resource in await client.list_resources()},
                "templates": {
                    template.uri_template
                    for template in await client.list_resource_templates()
                },
                "prompts": {prompt.name for prompt in await client.list_prompts()},
            }

    return await run()


async def _instructions(mcp: FastMCP) -> str | None:
    """Returns the instructions a client receives while connecting."""

    async def run() -> str | None:
        async with Client(mcp) as client:
            return client.instructions

    return await run()


async def test_every_context_is_mounted_once(server: MCPServer) -> None:
    """The parent mounts one sub-server per registered context, in order."""
    assert [context.name for context in server.contexts] == [
        "catalog",
        "comment",
        "conversation",
        "iam",
        "ingestion",
        "llm_config",
        "semantic",
        "vocabulary",
    ]


async def test_mounting_keeps_the_names_of_each_context(server: MCPServer) -> None:
    """Without a namespace the parent exposes exactly the union of its children."""
    parent = await _surface(server.mcp)
    children = [await _surface(context) for context in server.contexts]

    for surface in parent:
        assert parent[surface] == set().union(*(child[surface] for child in children))
    assert len(parent["tools"]) == 108
    assert len(parent["resources"]) == 10
    assert len(parent["templates"]) == 25
    assert len(parent["prompts"]) == 15


async def test_instructions_come_from_the_parent(server: MCPServer) -> None:
    """A mounted server's instructions are dropped, so the parent composes them."""
    assert await _instructions(server.mcp) == server_module.INSTRUCTIONS
    for context in server.contexts:
        assert await _instructions(context) == context.instructions


async def test_a_new_context_needs_no_change_to_the_server(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Registering a dummy context is enough for MCPServer to mount it."""
    monkeypatch.setattr(registry, "_FACTORIES", [])

    @registry.mcp_context("dummy", "Dummy context.")
    def register(mcp: FastMCP, container: object) -> None:
        @mcp.tool(name="dummy_tool", description="Dummy tool.")
        def dummy_tool() -> str:
            """Do nothing."""
            return "ok"

    server = MCPServer(object(), require_auth=False)  # type: ignore[arg-type]

    assert [context.name for context in server.contexts] == ["dummy"]
    assert (await _surface(server.mcp))["tools"] == {"dummy_tool"}
