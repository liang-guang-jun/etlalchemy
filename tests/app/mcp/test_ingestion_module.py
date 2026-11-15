"""Tests for the ingestion MCP primitives."""

import asyncio
import time
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from dependency_injector import providers

from etlalchemy.app.bootstrap import Container, run_container
from etlalchemy.app.mcp.server import MCPServer
from etlalchemy.ingestion.aggregates.import_run import ImportRun
from etlalchemy.ingestion.ports.data_source import ColumnInfo
from tests.app.mcp.support import (
    call_tool,
    list_prompts,
    list_resource_templates,
    list_resources,
    list_tools,
    read_resource,
)
from tests.ingestion.support import FakeSource, FakeSourceFactory

WAIT_TIMEOUT = 10.0

INGESTION_TOOLS = {
    "create_source_connection",
    "change_source_connection",
    "rotate_source_credential",
    "discard_source_connection",
    "import_source_catalog",
    "list_source_connections",
    "get_source_connection",
    "list_import_runs",
    "get_import_run",
    "list_source_kinds",
    "list_source_profiles",
    "inspect_source",
    "plan_import",
    "test_source_connection",
    "abandon_import_run",
}


async def wait_for(
    predicate: Callable[[], Any],
    timeout: float = WAIT_TIMEOUT,
) -> Any:
    """Polls ``predicate`` until it returns a truthy value."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = await predicate()
        if result:
            return result
        await asyncio.sleep(0.05)
    raise AssertionError("timed out waiting for the projection")


async def connections(server: MCPServer) -> list[dict[str, Any]]:
    """Returns the connection resource payload."""
    rows: list[dict[str, Any]] = await read_resource(server, "ingestion:///connections")
    return rows


async def test_ingestion_tools_are_registered(server: MCPServer) -> None:
    """The ingestion commands and parameterised reads are exposed."""
    names = {tool.name for tool in await list_tools(server)}

    assert INGESTION_TOOLS <= names


async def test_local_source_profiles_are_listed(
    fake_server: tuple[MCPServer, FakeSource, Container],
) -> None:
    """The local profile store is exposed as a read-only tool."""
    server, _, _ = fake_server
    result = await call_tool(server, "list_source_profiles", {"kind": "fake"})

    assert result.structured_content["result"] == [
        {"name": "fake", "host": "https://fake.test"}
    ]


async def test_ingestion_resources_and_prompt_are_registered(server: MCPServer) -> None:
    """Connections, runs and the workflow prompt are exposed."""
    uris = {str(resource.uri) for resource in await list_resources(server)}
    templates = {template.uri_template for template in await list_resource_templates(server)}
    prompts = {prompt.name for prompt in await list_prompts(server)}

    assert {"ingestion:///connections", "ingestion:///runs"} <= uris
    assert {
        "ingestion:///connections/{connection_id}",
        "ingestion:///runs/{run_id}",
    } <= templates
    assert "import-catalog-workflow" in prompts


async def test_connection_tools_and_resources_round_trip(server: MCPServer) -> None:
    """Connections can be created, changed, rotated and discarded through tools."""
    created = await call_tool(
        server,
        "create_source_connection",
        {
            "name": "warehouse",
            "endpoint": "https://example.test",
            "credential_ref": "env:DBX_TOKEN",
            "options": {"warehouse_id": "abc"},
        },
    )
    connection_id = created.structured_content["connection_id"]
    uri = f"ingestion:///connections/{connection_id}"

    rows = await wait_for(lambda: connections(server))
    assert [row["name"] for row in rows] == ["warehouse"]
    assert rows[0]["credential_ref"] == "env:DBX_TOKEN"
    assert rows[0]["has_inline_credential"] is False
    assert rows[0]["options"] == {"warehouse_id": "abc"}
    assert (await read_resource(server, uri))["kind"] == "databricks"

    changed = await call_tool(
        server,
        "change_source_connection",
        {"connection_id": connection_id, "name": "renamed"},
    )
    assert changed.structured_content == {"ok": True}

    async def renamed() -> bool:
        row = await read_resource(server, uri)
        return row is not None and row["name"] == "renamed"

    await wait_for(renamed)

    rotated = await call_tool(
        server,
        "rotate_source_credential",
        {"connection_id": connection_id, "token": "s3cr3t"},
    )
    assert rotated.structured_content == {"ok": True}

    async def rotated_inline() -> bool:
        row = await read_resource(server, uri)
        return row is not None and row["has_inline_credential"] is True

    await wait_for(rotated_inline)

    discarded = await call_tool(
        server,
        "discard_source_connection",
        {"connection_id": connection_id},
    )
    assert discarded.structured_content == {"ok": True}
    async def discarded_rows() -> bool:
        return await connections(server) == []

    await wait_for(discarded_rows)
    assert await read_resource(server, uri) is None


async def test_unknown_connection_is_reported_as_not_found(server: MCPServer) -> None:
    """An unknown connection comes back with the not_found prefix."""
    result = await call_tool(
        server,
        "change_source_connection",
        {"connection_id": str(uuid4()), "name": "renamed"},
        raise_on_error=False,
    )

    assert result.is_error is True
    assert "[not_found]" in result.content[0].text


async def test_unknown_kind_is_reported_as_conflict(server: MCPServer) -> None:
    """An unknown source kind comes back with the conflict prefix."""
    result = await call_tool(
        server,
        "create_source_connection",
        {
            "name": "warehouse",
            "kind": "unknown",
            "endpoint": "https://example.test",
            "token": "s3cr3t",
        },
        raise_on_error=False,
    )

    assert result.is_error is True
    assert "[conflict]" in result.content[0].text


async def test_runs_resource_is_empty_and_missing_run_is_null(server: MCPServer) -> None:
    """Missing runs answer null and malformed ids never raise."""
    assert await read_resource(server, "ingestion:///runs") == []
    assert await read_resource(server, f"ingestion:///runs/{uuid4()}") is None
    assert await read_resource(server, "ingestion:///runs/not-a-uuid") is None
    assert await read_resource(server, "ingestion:///connections/not-a-uuid") is None


@pytest.fixture
async def fake_server(
    config_dir: Path,
) -> AsyncIterator[tuple[MCPServer, FakeSource, Container]]:
    """Returns an MCP server whose ingestion factories build a fake source."""
    source = FakeSource(
        catalogs={
            "src": {
                "sales": {
                    "orders": [
                        ColumnInfo(name="id", raw_type="BIGINT", nullable=False),
                        ColumnInfo(name="amount", raw_type="DECIMAL(10,2)", nullable=True),
                    ]
                }
            }
        }
    )
    container = Container()
    container.source_factories.override(providers.Object({"fake": FakeSourceFactory(source)}))
    async with run_container(container):
        yield MCPServer(container), source, container


async def test_read_tools_expose_connections_and_kinds(server: MCPServer) -> None:
    """Connections and source kinds are readable through tools."""
    created = await call_tool(
        server,
        "create_source_connection",
        {
            "name": "warehouse",
            "endpoint": "https://example.test",
            "credential_ref": "env:DBX_TOKEN",
        },
    )
    connection_id = created.structured_content["connection_id"]

    async def listed() -> list[dict[str, Any]]:
        result = await call_tool(server, "list_source_connections", {})
        rows: list[dict[str, Any]] = result.structured_content["result"]
        return rows

    rows = await wait_for(listed)
    assert [row["name"] for row in rows] == ["warehouse"]

    fetched = await call_tool(server, "get_source_connection", {"connection_id": connection_id})
    assert fetched.structured_content["result"]["name"] == "warehouse"

    kinds_result = await call_tool(server, "list_source_kinds", {})
    assert {row["kind"] for row in kinds_result.structured_content["result"]} == {
        "databricks",
        "postgres",
    }

    missing = await call_tool(server, "get_source_connection", {"connection_id": str(uuid4())})
    assert missing.structured_content == {"result": None}


async def test_import_run_read_tools_and_abandon(
    server: MCPServer,
    container: Container,
) -> None:
    """Runs can be listed, fetched and abandoned."""
    run = ImportRun(connection_id=uuid4(), target_catalog_id=uuid4())
    await container.ingestion_application().save(run)
    run_uri = f"ingestion:///runs/{run.id}"

    async def started() -> bool:
        return await read_resource(server, run_uri) is not None

    await wait_for(started)

    listed = await call_tool(server, "list_import_runs", {"status": "pending"})
    assert [row["run_id"] for row in listed.structured_content["result"]] == [str(run.id)]

    fetched = await call_tool(server, "get_import_run", {"run_id": str(run.id)})
    assert fetched.structured_content["result"]["status"] == "pending"

    abandoned = await call_tool(
        server,
        "abandon_import_run",
        {"run_id": str(run.id), "reason": "crashed"},
    )
    assert abandoned.structured_content == {"ok": True}

    async def abandoned_row() -> bool:
        row = await read_resource(server, run_uri)
        return row is not None and row["status"] == "abandoned"

    await wait_for(abandoned_row)
    assert (await read_resource(server, run_uri))["error"] == "crashed"


async def test_plan_test_and_import_tools(
    fake_server: tuple[MCPServer, FakeSource, Container],
) -> None:
    """Inspection, planning, probing and import work against a fake source."""
    server, _, _ = fake_server
    created = await call_tool(
        server,
        "create_source_connection",
        {
            "name": "fake-source",
            "kind": "fake",
            "endpoint": "https://example.test",
            "token": "s3cr3t",
        },
    )
    connection_id = created.structured_content["connection_id"]
    catalog_result = await call_tool(server, "create_catalog", {"name": "target"})
    catalog_id = catalog_result.structured_content["catalog_id"]

    inspected_result = await call_tool(
        server,
        "inspect_source",
        {
            "connection_id": connection_id,
            "catalog": "src",
            "schema": "sales",
            "table": "orders",
        },
    )
    inspected = inspected_result.structured_content
    assert inspected["node"] == "columns"
    assert [(item["name"], item["mapped_type"]) for item in inspected["items"]] == [
        ("id", "bigint"),
        ("amount", "decimal(10,2)"),
    ]

    planned_result = await call_tool(
        server,
        "plan_import",
        {
            "connection_id": connection_id,
            "target_catalog_id": catalog_id,
            "source_catalog": "src",
            "include_tables": {"sales": ["orders"]},
            "schema_mapping": {"sales": "sales_raw"},
        },
    )
    planned = planned_result.structured_content
    assert planned["schema_count"] == 1
    assert planned["new_schemas"] == ["sales_raw"]
    assert planned["new_tables"] == ["sales_raw.orders"]
    assert planned["field_count"] == 2
    assert planned["warnings"] == []

    tested_result = await call_tool(
        server,
        "test_source_connection",
        {"connection_id": connection_id},
    )
    assert tested_result.structured_content["ok"] is True

    imported_result = await call_tool(
        server,
        "import_source_catalog",
        {
            "connection_id": connection_id,
            "target_catalog_id": catalog_id,
            "source_catalog": "src",
            "include_tables": {"sales": ["orders"]},
            "schema_mapping": {"sales": "sales_raw"},
        },
    )
    imported = imported_result.structured_content
    assert imported["status"] == "succeeded"
    assert imported["include_tables"] == {"sales": ["orders"]}
    assert imported["schema_mapping"] == {"sales": "sales_raw"}
    assert (
        imported["schema_count"],
        imported["table_count"],
        imported["field_count"],
    ) == (1, 1, 2)

    schemas = await wait_for(
        lambda: read_resource(server, f"catalog:///{catalog_id}/schemas")
    )
    assert [row["name"] for row in schemas] == ["sales_raw"]
