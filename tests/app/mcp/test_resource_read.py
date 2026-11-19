"""Tests for reading catalog resources through the MCP server."""

import asyncio
import time
from collections.abc import Callable
from typing import Any
from uuid import uuid4

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


async def create_catalog(server: MCPServer, name: str = "analytics") -> str:
    """Creates a catalog through the tool surface and returns its id."""
    result = await call_tool(server, "create_catalog", {"name": name})
    catalog_id: str = result.structured_content["catalog_id"]
    return catalog_id


async def create_tree(server: MCPServer) -> tuple[str, str, str]:
    """Creates a catalog, a schema, a table and a field, returning the ids."""
    catalog_id = await create_catalog(server)
    schema = await call_tool(
        server,
        "create_schema",
        {"catalog_id": catalog_id, "schema_name": "sales", "description": "Sales data"},
    )
    schema_id = schema.structured_content["schema_id"]
    table = await call_tool(
        server,
        "add_table",
        {"catalog_id": catalog_id, "schema": "sales", "table_name": "orders"},
    )
    table_id = table.structured_content["table_id"]
    await call_tool(
        server,
        "add_field",
        {
            "catalog_id": catalog_id,
            "schema": "sales",
            "table": "orders",
            "field_name": "id",
            "data_type": "integer",
            "nullable": False,
        },
    )
    return catalog_id, schema_id, table_id


async def test_all_catalogs_lists_created_catalog(server: MCPServer) -> None:
    """The catalog collection reflects the projection."""
    catalog_id = await create_catalog(server)

    await wait_for(lambda: read_resource(server, "catalog:///all"))
    assert await read_resource(server, "catalog:///all") == [
        {"catalog_id": catalog_id, "name": "analytics", "description": ""}
    ]


async def test_single_catalog_resource_returns_the_row(server: MCPServer) -> None:
    """One catalog is addressable by its id."""
    catalog_id = await create_catalog(server)
    uri = f"catalog:///{catalog_id}"

    async def created() -> bool:
        return await read_resource(server, uri) is not None

    await wait_for(created)
    assert (await read_resource(server, uri))["name"] == "analytics"


async def test_schema_resources_follow_the_hierarchy(server: MCPServer) -> None:
    """The schema collection and the schema resource are addressable."""
    catalog_id, schema_id, _ = await create_tree(server)
    collection = f"catalog:///{catalog_id}/schemas"
    single = f"{collection}/{schema_id}"

    async def listed() -> bool:
        return bool(await read_resource(server, collection))

    await wait_for(listed)
    rows = await read_resource(server, collection)
    assert [(row["schema_id"], row["name"]) for row in rows] == [(schema_id, "sales")]
    assert (await read_resource(server, single))["description"] == "Sales data"


async def test_table_and_field_resources_follow_the_hierarchy(server: MCPServer) -> None:
    """Tables and fields are reachable through their parents."""
    catalog_id, schema_id, table_id = await create_tree(server)
    tables = f"catalog:///{catalog_id}/schemas/{schema_id}/tables"
    fields = f"{tables}/{table_id}/fields"

    async def described() -> bool:
        return bool(await read_resource(server, fields))

    await wait_for(described)
    assert [row["table_id"] for row in await read_resource(server, tables)] == [table_id]
    assert (await read_resource(server, f"{tables}/{table_id}"))["name"] == "orders"
    assert [
        (row["name"], row["data_type"], row["nullable"])
        for row in await read_resource(server, fields)
    ] == [("id", "integer", False)]


async def test_missing_objects_answer_null_or_empty(server: MCPServer) -> None:
    """Resources read, they do not fail: unknown ids answer null or []."""
    await create_catalog(server)
    unknown = uuid4()

    assert await read_resource(server, f"catalog:///{unknown}") is None
    assert await read_resource(server, f"catalog:///{unknown}/schemas") == []
    assert await read_resource(server, "catalog:///not-a-uuid") is None
    assert await read_resource(server, "catalog:///not-a-uuid/schemas") == []
    assert await read_resource(server, f"catalog:///{unknown}/schemas/{unknown}") is None
