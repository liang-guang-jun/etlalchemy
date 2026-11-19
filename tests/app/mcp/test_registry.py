"""Tests for the MCP context registry."""

from __future__ import annotations

from typing import Any

import pytest
from etlalchemy.app.mcp import registry
from fastmcp import Client, FastMCP


async def _tool_names(server: FastMCP) -> set[str]:
    """Returns the tools a server exposes."""

    async def run() -> set[str]:
        async with Client(server) as client:
            return {tool.name for tool in await client.list_tools()}

    return await run()


@pytest.fixture
async def empty_registry(monkeypatch: pytest.MonkeyPatch) -> list[registry.ContextFactory]:
    """Replaces the registry contents so tests never leak dummy contexts."""
    factories: list[registry.ContextFactory] = []
    monkeypatch.setattr(registry, "_FACTORIES", factories)
    return factories


async def test_decoration_only_records_the_factory(
    empty_registry: list[registry.ContextFactory],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Importing a context package must not build a server."""

    def explode(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("FastMCP must not be built at import time")

    monkeypatch.setattr(FastMCP, "__init__", explode)

    def register(mcp: FastMCP, container: Any) -> None:
        """Do nothing."""

    decorated = registry.mcp_context("probe", "Probe instructions.")(register)

    assert decorated is register
    assert [(name, text) for name, text, _ in empty_registry] == [("probe", "Probe instructions.")]


async def test_build_contexts_follows_registration_order(
    empty_registry: list[registry.ContextFactory],
) -> None:
    """One server is built per context, in the order the packages registered."""
    calls: list[tuple[str, object]] = []
    container = object()

    def first(server: FastMCP, passed: object) -> None:
        """Record the first call."""
        calls.append((server.name, passed))

    def second(server: FastMCP, passed: object) -> None:
        """Record the second call."""
        calls.append((server.name, passed))

    registry.mcp_context("first", "One.")(first)
    registry.mcp_context("second", "Two.")(second)

    servers = registry.build_contexts(container)  # type: ignore[arg-type]

    assert [server.name for server in servers] == ["first", "second"]
    assert [server.instructions for server in servers] == ["One.", "Two."]
    assert calls == [("first", container), ("second", container)]


async def test_build_contexts_populates_each_server(
    empty_registry: list[registry.ContextFactory],
) -> None:
    """The decorated function receives its own server and fills it."""

    @registry.mcp_context("dummy", "Dummy context.")
    def register(mcp: FastMCP, container: object) -> None:
        @mcp.tool(name="dummy_tool", description="Dummy tool.")
        def dummy_tool() -> str:
            """Do nothing."""
            return "ok"

    servers = registry.build_contexts(object())  # type: ignore[arg-type]

    assert [server.name for server in servers] == ["dummy"]
    assert await _tool_names(servers[0]) == {"dummy_tool"}


async def test_duplicate_context_name_is_rejected(empty_registry: list[registry.ContextFactory]) -> None:
    """Registering the same name twice fails while the module is imported."""

    def register(mcp: FastMCP, container: Any) -> None:
        """Do nothing."""

    registry.mcp_context("twin")(register)

    with pytest.raises(ValueError, match="duplicate MCP context name"):
        registry.mcp_context("twin")(register)


async def test_builtin_contexts_register_in_import_order() -> None:
    """The package imports in `server.py` decide the mount order."""
    assert [name for name, _, _ in registry.contexts()] == [
        "catalog",
        "comment",
        "conversation",
        "iam",
        "ingestion",
        "llm_config",
        "semantic",
        "vocabulary",
    ]
