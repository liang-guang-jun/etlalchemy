"""Tests for the MCP call logging middleware."""

from __future__ import annotations

from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any

import pytest
from etlalchemy.app.mcp.server import MCPServer
from etlalchemy.shared.logging import configure_logging, reset_logging
from structlog.testing import capture_logs

from tests.app.mcp.support import call_tool, read_resource


async def settings() -> SimpleNamespace:
    """Returns logging settings that keep every level visible."""
    values: dict[str, Any] = {
        "level": "DEBUG",
        "mode": "json",
        "color": False,
        "quiet": [],
        "loggers": {},
    }
    return SimpleNamespace(**values)


@pytest.fixture(autouse=True)
async def _logging() -> Iterator[None]:
    """Configures logging once and restores the process state afterwards."""
    reset_logging()
    configure_logging(await settings())
    yield
    reset_logging()


async def test_tool_calls_are_logged(server: MCPServer) -> None:
    """A tool call is visible with its name and duration."""
    with capture_logs() as logs:
        await call_tool(server, "create_catalog", {"name": "analytics"})

    entry = next(entry for entry in logs if entry["event"] == "mcp.tool")
    assert entry["tool"] == "create_catalog"
    assert "duration_ms" in entry


async def test_resource_reads_are_logged(server: MCPServer) -> None:
    """A resource read is visible with its URI."""
    with capture_logs() as logs:
        await read_resource(server, "catalog:///all")

    entry = next(entry for entry in logs if entry["event"] == "mcp.resource")
    assert entry["resource"] == "catalog:///all"
    assert "duration_ms" in entry
