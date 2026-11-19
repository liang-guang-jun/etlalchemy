"""Tests for the semantic context MCP primitives."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from typing import Any

from etlalchemy.app.mcp.server import MCPServer

from tests.app.mcp.support import (
    call_tool,
    list_prompts,
    list_resource_templates,
    list_resources,
    list_tools,
    read_resource,
)

WAIT_TIMEOUT = 10.0

SEMANTIC_TOOLS = {
    "create_model",
    "change_model",
    "discard_model",
    "add_entity",
    "rename_entity",
    "change_entity_table",
    "remove_entity",
    "add_relationship",
    "change_relationship",
    "remove_relationship",
    "add_diagram",
    "rename_diagram",
    "change_diagram_order",
    "remove_diagram",
    "place_node",
    "move_node",
    "remove_node",
    "list_models",
    "get_model",
    "list_entities",
    "get_entity",
    "list_relationships",
    "get_relationship",
    "list_diagrams",
    "get_diagram",
    "list_nodes",
}

SEMANTIC_TEMPLATES = {
    "semantic:///models/{model_id}",
    "semantic:///models/{model_id}/entities",
    "semantic:///models/{model_id}/relationships",
    "semantic:///models/{model_id}/diagrams",
    "semantic:///models/{model_id}/diagrams/{name}",
    "semantic:///models/{model_id}/diagrams/{name}/nodes",
}

SEMANTIC_PROMPTS = {"model-from-catalog", "review-model"}


async def wait_for(predicate: Callable[[], Any], timeout: float = WAIT_TIMEOUT) -> Any:
    """Polls ``predicate`` until it returns a truthy value."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = await predicate()
        if result:
            return result
        await asyncio.sleep(0.05)
    raise AssertionError("timed out waiting for the projection")


async def create_catalog_tables(server: MCPServer) -> dict[str, str]:
    """Creates a catalog with two tables and returns the table ids."""
    catalog = await call_tool(server, "create_catalog", {"name": "analytics"})
    catalog_id = catalog.structured_content["catalog_id"]
    schema = await call_tool(
        server,
        "create_schema",
        {"catalog_id": catalog_id, "schema_name": "sales"},
    )
    schema_id = schema.structured_content["schema_id"]
    tables: dict[str, str] = {}
    for table_name, fields in (
        ("customers", ("id",)),
        ("orders", ("id", "customer_id")),
    ):
        created = await call_tool(
            server,
            "add_table",
            {"catalog_id": catalog_id, "schema": "sales", "table_name": table_name},
        )
        table_id = created.structured_content["table_id"]
        tables[table_name] = table_id
        for field_name in fields:
            await call_tool(
                server,
                "add_field",
                {
                    "catalog_id": catalog_id,
                    "schema": "sales",
                    "table": table_name,
                    "field_name": field_name,
                    "data_type": "integer",
                    "nullable": False,
                },
            )

        fields_uri = (
            f"catalog:///{catalog_id}/schemas/{schema_id}/tables/{table_id}/fields"
        )

        async def fields_ready(uri: str = fields_uri, expected: int = len(fields)) -> bool:
            return len(await read_resource(server, uri)) == expected

        await wait_for(fields_ready)
    return tables


async def create_model(server: MCPServer) -> tuple[str, dict[str, str]]:
    """Creates a model with the customers and orders entities."""
    tables = await create_catalog_tables(server)
    model = await call_tool(server, "create_model", {"name": "sales", "description": "Revenue"})
    model_id = model.structured_content["model_id"]
    for name in ("customers", "orders"):
        await call_tool(
            server,
            "add_entity",
            {"model_id": model_id, "entity_name": name, "table_id": tables[name]},
        )

    async def entities_ready() -> bool:
        payload = await read_resource(server, f"semantic:///models/{model_id}/entities")
        return len(payload) == 2

    await wait_for(entities_ready)
    return model_id, tables


async def test_semantic_registers_all_primitives(server: MCPServer) -> None:
    """The semantic context exposes its tools, resources and prompts."""
    tools = {tool.name for tool in await list_tools(server)}
    resources = {str(resource.uri) for resource in await list_resources(server)}
    templates = {template.uri_template for template in await list_resource_templates(server)}
    prompts = {prompt.name for prompt in await list_prompts(server)}

    assert tools >= SEMANTIC_TOOLS
    assert "semantic:///models" in resources
    assert templates >= SEMANTIC_TEMPLATES
    assert prompts >= SEMANTIC_PROMPTS


async def test_semantic_workflow_over_mcp(server: MCPServer) -> None:
    """Entities, a relationship, diagrams and nodes round-trip over MCP."""
    model_id, tables = await create_model(server)
    relationship = await call_tool(
        server,
        "add_relationship",
        {
            "model_id": model_id,
            "from_refs": [{"entity": "customers", "field": "id"}],
            "to_refs": [{"entity": "orders", "field": "customer_id"}],
            "cardinality": "one_to_many",
            "filter_direction": "both",
        },
    )
    relationship_id = relationship.structured_content["relationship_id"]
    await call_tool(
        server,
        "add_diagram",
        {"model_id": model_id, "name": "detail", "order": 1},
    )
    node = await call_tool(
        server,
        "place_node",
        {
            "model_id": model_id,
            "diagram_name": "detail",
            "entity_name": "orders",
            "x": 10.0,
            "y": 20.0,
        },
    )
    assert node.structured_content["diagram_name"] == "detail"

    async def nodes_ready() -> bool:
        payload = await read_resource(server, f"semantic:///models/{model_id}/diagrams/detail/nodes")
        return [row["entity_name"] for row in payload] == ["orders"]

    await wait_for(nodes_ready)

    entity = await call_tool(
        server,
        "get_entity",
        {"model_id": model_id, "entity_name": "customers"},
    )
    assert entity.structured_content["result"]["table_id"] == tables["customers"]
    relationships = await read_resource(server, f"semantic:///models/{model_id}/relationships")
    assert [row["relationship_id"] for row in relationships] == [relationship_id]
    assert relationships[0]["from_refs"] == [{"entity": "customers", "field": "id"}]

    moved = await call_tool(
        server,
        "move_node",
        {
            "model_id": model_id,
            "diagram_name": "All",
            "entity_name": "orders",
            "x": 100.0,
            "y": 200.0,
        },
    )
    assert moved.structured_content is None or "ok" in str(moved.structured_content)

    renamed = await call_tool(
        server,
        "rename_entity",
        {"model_id": model_id, "old_name": "customers", "new_name": "clients"},
    )
    assert renamed.structured_content is not None

    async def rename_visible() -> bool:
        payload = await read_resource(server, f"semantic:///models/{model_id}/entities")
        return [row["name"] for row in payload] == ["clients", "orders"]

    await wait_for(rename_visible)
    discarded = await call_tool(server, "discard_model", {"model_id": model_id})
    assert discarded.structured_content is not None

    async def model_gone() -> bool:
        payload = await read_resource(server, f"semantic:///models/{model_id}")
        return payload is None

    await wait_for(model_gone)


async def test_the_all_diagram_rejects_manual_nodes_over_mcp(server: MCPServer) -> None:
    """Placing or removing an All node reports a conflict, moving one works."""
    model_id, _ = await create_model(server)

    placed = await call_tool(
        server,
        "place_node",
        {
            "model_id": model_id,
            "diagram_name": "All",
            "entity_name": "orders",
            "x": 1.0,
            "y": 1.0,
        },
        raise_on_error=False,
    )
    removed = await call_tool(
        server,
        "remove_node",
        {"model_id": model_id, "diagram_name": "All", "entity_name": "orders"},
        raise_on_error=False,
    )
    moved = await call_tool(
        server,
        "move_node",
        {
            "model_id": model_id,
            "diagram_name": "All",
            "entity_name": "orders",
            "x": 5.0,
            "y": 6.0,
        },
    )

    assert placed.is_error is True
    assert "[conflict]" in placed.content[0].text
    assert removed.is_error is True
    assert "[conflict]" in removed.content[0].text
    assert moved.structured_content is not None


async def test_semantic_errors_use_the_bracketed_prefixes(server: MCPServer) -> None:
    """A bad field reference is a conflict and an unknown model is not found."""
    model_id, _ = await create_model(server)

    bad_field = await call_tool(
        server,
        "add_relationship",
        {
            "model_id": model_id,
            "from_refs": [{"entity": "customers", "field": "id"}],
            "to_refs": [{"entity": "orders", "field": "ghost"}],
            "cardinality": "one_to_many",
        },
        raise_on_error=False,
    )
    missing = await call_tool(
        server,
        "get_model",
        {"model_id": "00000000-0000-0000-0000-000000000000"},
        raise_on_error=False,
    )

    assert bad_field.is_error is True
    assert "[conflict]" in bad_field.content[0].text
    assert missing.structured_content in (None, {"result": None})


async def test_read_resources_are_null_for_unknown_ids(server: MCPServer) -> None:
    """Resources answer null or [] instead of raising for unknown ids."""
    missing = "00000000-0000-0000-0000-000000000000"

    assert await read_resource(server, f"semantic:///models/{missing}") is None
    assert await read_resource(server, f"semantic:///models/{missing}/entities") == []
    assert await read_resource(server, "semantic:///models/not-a-uuid") is None
