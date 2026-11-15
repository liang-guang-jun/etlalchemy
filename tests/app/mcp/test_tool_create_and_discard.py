"""Tests for calling catalog MCP tools and reading their errors."""

import asyncio
import time
from collections.abc import Callable
from typing import Any

from etlalchemy.app.mcp.server import MCPServer
from tests.app.mcp.support import call_tool, read_resource

WAIT_TIMEOUT = 10.0


async def wait_for(predicate: Callable[[], Any], timeout: float = WAIT_TIMEOUT) -> None:
    """Polls ``predicate`` until it returns a truthy value."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if await predicate():
            return
        await asyncio.sleep(0.05)
    raise AssertionError("timed out waiting for the projection")


async def assert_ok(
    server: MCPServer,
    name: str,
    arguments: dict[str, Any],
) -> None:
    """Calls a tool and asserts that it answered the generic ok payload."""
    result = await call_tool(server, name, arguments)
    assert result.structured_content == {"ok": True}, name


async def create_catalog(server: MCPServer) -> str:
    """Creates a catalog through the tool surface and returns its id."""
    result = await call_tool(server, "create_catalog", {"name": "analytics"})
    catalog_id: str = result.structured_content["catalog_id"]
    return catalog_id


async def test_discard_catalog_removes_it_from_the_resources(server: MCPServer) -> None:
    """A discarded catalog disappears from the read resources."""
    catalog_id = await create_catalog(server)
    uri = f"catalog:///{catalog_id}"

    async def created() -> bool:
        return await read_resource(server, uri) is not None

    await wait_for(created)

    discarded = await call_tool(server, "discard_catalog", {"catalog_id": catalog_id})

    assert discarded.structured_content == {"ok": True}

    async def removed() -> bool:
        return await read_resource(server, uri) is None

    await wait_for(removed)
    assert await read_resource(server, "catalog:///all") == []


async def test_duplicate_schema_is_reported_as_conflict(server: MCPServer) -> None:
    """A duplicated name comes back with the conflict prefix."""
    catalog_id = await create_catalog(server)
    arguments = {"catalog_id": catalog_id, "schema_name": "sales"}
    await call_tool(server, "create_schema", arguments)

    result = await call_tool(server, "create_schema", arguments, raise_on_error=False)

    assert result.is_error is True
    assert "[conflict]" in result.content[0].text


async def test_unknown_schema_is_reported_as_not_found(server: MCPServer) -> None:
    """An unknown reference comes back with the not_found prefix."""
    catalog_id = await create_catalog(server)

    result = await call_tool(
        server,
        "add_table",
        {"catalog_id": catalog_id, "schema": "warehouse", "table_name": "orders"},
        raise_on_error=False,
    )

    assert result.is_error is True
    assert "[not_found]" in result.content[0].text


async def test_field_tools_round_trip(server: MCPServer) -> None:
    """Fields can be added, changed, renamed and removed through the tools."""
    catalog_id = await create_catalog(server)
    await call_tool(server, "create_schema", {"catalog_id": catalog_id, "schema_name": "sales"})
    await call_tool(
        server,
        "add_table",
        {"catalog_id": catalog_id, "schema": "sales", "table_name": "orders"},
    )
    field_arguments = {
        "catalog_id": catalog_id,
        "schema": "sales",
        "table": "orders",
        "field_name": "id",
        "data_type": "integer",
    }

    await assert_ok(server, "add_field", field_arguments)
    await assert_ok(server, "change_field", {**field_arguments, "data_type": "bigint"})
    await assert_ok(
        server,
        "rename_field",
        {
            "catalog_id": catalog_id,
            "schema": "sales",
            "table": "orders",
            "old_name": "id",
            "new_name": "order_id",
        },
    )
    await assert_ok(
        server,
        "remove_field",
        {
            "catalog_id": catalog_id,
            "schema": "sales",
            "table": "orders",
            "field_name": "order_id",
        },
    )
