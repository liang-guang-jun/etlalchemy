"""Tests for the vocabulary context MCP primitives."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from typing import Any
from uuid import uuid4

from etlalchemy.app.mcp.server import MCPServer
from tests.app.mcp.support import (
    call_tool,
    get_prompt,
    list_prompts,
    list_resource_templates,
    list_resources,
    list_tools,
    read_resource,
)

WAIT_TIMEOUT = 10.0

VOCABULARY_TOOLS = {
    "create_domain",
    "change_domain",
    "discard_domain",
    "create_term",
    "change_term_color",
    "change_term_definition",
    "add_term_alias",
    "remove_term_alias",
    "rename_term",
    "move_term",
    "approve_term",
    "reopen_term",
    "deprecate_term",
    "reactivate_term",
    "link_term",
    "unlink_term",
    "discard_term",
    "list_domains",
    "get_domain",
    "list_terms",
    "get_term",
    "list_children",
    "list_descendants",
    "search_terms",
    "list_terms_for_target",
    "list_terms_for_table",
    "list_terms_for_field",
}

VOCABULARY_TEMPLATES = {
    "vocabulary:///domains/{domain_id}",
    "vocabulary:///domains/{domain_id}/terms",
    "vocabulary:///terms/{term_id}",
    "vocabulary:///terms/{term_id}/children",
    "vocabulary:///terms/{term_id}/descendants",
}

VOCABULARY_PROMPTS = {"define-field", "review-vocabulary", "explain-table"}


async def wait_for(predicate: Callable[[], Any], timeout: float = WAIT_TIMEOUT) -> Any:
    """Polls ``predicate`` until it returns a truthy value."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = await predicate()
        if result:
            return result
        await asyncio.sleep(0.05)
    raise AssertionError("timed out waiting for the projection")


async def create_tree(server: MCPServer) -> tuple[str, str, str]:
    """Creates a domain, a root term and a child term through the tool surface."""
    domain = await call_tool(server, "create_domain", {"name": "finance"})
    domain_id = domain.structured_content["domain_id"]
    root = await call_tool(
        server,
        "create_term",
        {"domain_id": domain_id, "term_name": "Revenue", "definition": "Recognized revenue"},
    )
    root_id = root.structured_content["term_id"]
    child = await call_tool(
        server,
        "create_term",
        {
            "domain_id": domain_id,
            "term_name": "ARR",
            "definition": "Annual recurring revenue",
            "parent": "Revenue",
        },
    )
    return domain_id, root_id, child.structured_content["term_id"]


async def _terms(server: MCPServer, domain_id: str) -> list[dict[str, Any]]:
    """Returns the domain terms resource."""
    return await read_resource(server, f"vocabulary:///domains/{domain_id}/terms")


async def test_vocabulary_registers_all_primitives(server: MCPServer) -> None:
    """The vocabulary context exposes its tools, resources and prompts."""
    tools = {tool.name for tool in await list_tools(server)}
    resources = {str(resource.uri) for resource in await list_resources(server)}
    templates = {template.uri_template for template in await list_resource_templates(server)}
    prompts = {prompt.name for prompt in await list_prompts(server)}

    assert VOCABULARY_TOOLS <= tools
    assert "vocabulary:///domains" in resources
    assert VOCABULARY_TEMPLATES <= templates
    assert VOCABULARY_PROMPTS <= prompts


async def test_vocabulary_tree_workflow_over_mcp(server: MCPServer) -> None:
    """A tree can be created, repathed, moved and discarded through MCP."""
    domain_id, root_id, child_id = await create_tree(server)

    async def both_terms() -> list[dict[str, Any]] | None:
        rows = await _terms(server, domain_id)
        expected = ["Revenue", "Revenue/ARR"]
        return rows if sorted(row["path"] for row in rows) == expected else None

    terms = await wait_for(both_terms)
    assert sorted(row["path"] for row in terms) == ["Revenue", "Revenue/ARR"]

    roots = await call_tool(server, "list_children", {"domain_id": domain_id})
    assert [row["term_id"] for row in roots.structured_content["result"]] == [root_id]
    children = await call_tool(
        server,
        "list_children",
        {"domain_id": domain_id, "term": "Revenue"},
    )
    assert [row["term_id"] for row in children.structured_content["result"]] == [child_id]

    await call_tool(server, "rename_term", {"domain_id": domain_id, "term": root_id, "new_name": "Sales"})

    async def renamed() -> bool:
        row = await read_resource(server, f"vocabulary:///terms/{child_id}")
        return row is not None and row["path"] == "Sales/ARR"

    await wait_for(renamed)
    descendants = await call_tool(
        server,
        "list_descendants",
        {"domain_id": domain_id, "term": root_id},
    )
    assert [row["term_id"] for row in descendants.structured_content["result"]] == [child_id]

    cycle = await call_tool(
        server,
        "move_term",
        {"domain_id": domain_id, "term": root_id, "new_parent": "Sales/ARR"},
        raise_on_error=False,
    )
    assert cycle.is_error is True
    assert "[conflict]" in cycle.content[0].text

    await call_tool(
        server,
        "move_term",
        {"domain_id": domain_id, "term": child_id, "new_parent": None},
    )

    async def moved() -> bool:
        row = await read_resource(server, f"vocabulary:///terms/{child_id}")
        return row is not None and row["path"] == "ARR" and row["parent_id"] is None

    await wait_for(moved)
    search = await call_tool(server, "search_terms", {"query": "annual"})
    assert [row["term_id"] for row in search.structured_content["result"]] == [child_id]

    await call_tool(server, "discard_term", {"domain_id": domain_id, "term": root_id})

    async def discarded() -> bool:
        return all(row["path"] != "Sales" for row in await _terms(server, domain_id))

    await wait_for(discarded)
    assert await read_resource(server, f"vocabulary:///terms/{root_id}") is None


async def test_get_term_matches_the_term_resource(server: MCPServer) -> None:
    """The tool and the resource render the same resolved link payload."""
    domain_id, root_id, _ = await create_tree(server)
    catalog = await call_tool(server, "create_catalog", {"name": "analytics"})
    catalog_id = catalog.structured_content["catalog_id"]
    await wait_for(lambda: read_resource(server, f"catalog:///{catalog_id}"))
    await call_tool(
        server,
        "link_term",
        {
            "domain_id": domain_id,
            "term": root_id,
            "target_id": catalog_id,
            "target_kind": "catalog",
        },
    )

    async def linked_resource() -> dict[str, Any] | None:
        payload = await read_resource(server, f"vocabulary:///terms/{root_id}")
        if payload is not None and payload["links"]:
            return payload
        return None

    resource_payload = await wait_for(linked_resource)
    tool_result = await call_tool(server, "get_term", {"term_id": root_id})

    assert resource_payload["links"] == tool_result.structured_content["result"]["links"]
    assert resource_payload["links"][0]["status"] == "resolved"
    assert resource_payload["links"][0]["target_name"] == "analytics"


async def test_vocabulary_errors_use_the_bracket_prefixes(server: MCPServer) -> None:
    """Unknown references are not_found and rejected commands are conflicts."""
    domain_id, _, _ = await create_tree(server)

    missing = await call_tool(
        server,
        "approve_term",
        {"domain_id": domain_id, "term": str(uuid4())},
        raise_on_error=False,
    )
    duplicate = await call_tool(
        server,
        "create_term",
        {"domain_id": domain_id, "term_name": "Revenue", "definition": "dup"},
        raise_on_error=False,
    )
    missing_parent = await call_tool(
        server,
        "create_term",
        {"domain_id": domain_id, "term_name": "Forecast", "definition": "x", "parent": "Missing"},
        raise_on_error=False,
    )

    assert missing.is_error is True
    assert "[not_found]" in missing.content[0].text
    assert duplicate.is_error is True
    assert "[conflict]" in duplicate.content[0].text
    assert missing_parent.is_error is True
    assert "[not_found]" in missing_parent.content[0].text


async def test_vocabulary_prompts_render(server: MCPServer) -> None:
    """The English prompts point at the vocabulary resources."""
    field_prompt = await get_prompt(
        server,
        "define-field",
        {"catalog_id": "c-1", "schema_id": "s-1", "table_id": "t-1", "field_name": "amount"},
    )
    review_prompt = await get_prompt(server, "review-vocabulary", {"domain_id": "d-1"})

    assert "list_terms_for_field" in field_prompt.messages[0].content.text
    assert "vocabulary:///domains/d-1/terms" in review_prompt.messages[0].content.text
    assert "list_children" in review_prompt.messages[0].content.text


async def test_change_term_color_over_mcp(server: MCPServer) -> None:
    """The colour tool normalises the value and shows up in the term resource."""
    domain_id, root_id, _ = await create_tree(server)

    await call_tool(
        server,
        "change_term_color",
        {"domain_id": domain_id, "term": root_id, "color": "#ABC"},
    )

    async def coloured() -> dict[str, Any] | None:
        row = await read_resource(server, f"vocabulary:///terms/{root_id}")
        return row if row is not None and row["color"] == "#aabbcc" else None

    assert (await wait_for(coloured))["color"] == "#aabbcc"

    invalid = await call_tool(
        server,
        "change_term_color",
        {"domain_id": domain_id, "term": root_id, "color": "amber"},
        raise_on_error=False,
    )
    assert invalid.is_error is True
    assert "[conflict]" in invalid.content[0].text
    assert "#f2c811" in invalid.content[0].text
