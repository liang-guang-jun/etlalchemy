"""Tests for the comment context MCP primitives."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from typing import Any
from uuid import uuid4

from dependency_injector import providers
from etlalchemy.app.bootstrap import Container
from etlalchemy.app.mcp.server import MCPServer

from tests.app.mcp.support import (
    call_tool,
    list_prompts,
    list_resource_templates,
    list_tools,
    read_resource,
)

PASSWORD = "correct-horse-battery"
WAIT_TIMEOUT = 10.0

COMMENT_TOOLS = {
    "create_thread",
    "add_comment",
    "edit_comment",
    "discard_comment",
    "resolve_thread",
    "reopen_thread",
    "discard_thread",
    "list_threads",
    "get_thread",
    "list_comments",
}

COMMENT_TEMPLATES = {
    "comment:///threads/{thread_id}",
    "comment:///threads/{thread_id}/comments",
    "comment:///targets/{target_type}/{target_id}/threads",
}

COMMENT_PROMPTS = {
    "review-thread",
    "resolve-discussion",
    "draft-reply",
    "open-thread-for-target",
}


async def wait_for(predicate: Callable[[], Any], timeout: float = WAIT_TIMEOUT) -> Any:
    """Polls ``predicate`` until it returns a truthy value."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = await predicate()
        if result:
            return result
        await asyncio.sleep(0.05)
    raise AssertionError("timed out waiting for the projection")


async def create_session(container: Container) -> str:
    """Bootstraps an administrator, logs in and points the tools at its session."""
    iam = container.iam_application()
    await iam.bootstrap_admin("root@example.com", PASSWORD)

    async def identity_ready() -> bool:
        row = await container.iam_view().find_password_identity("root@example.com")
        return row is not None and await container.iam_view().get_password_hash(row.identity_id) is not None

    await wait_for(identity_ready)
    session = await iam.authenticate_password("root@example.com", PASSWORD)

    async def session_ready() -> bool:
        return await container.iam_view().get_session(session.session_id) is not None

    await wait_for(session_ready)
    container.mcp_session_resolver.override(providers.Object(session.session_id))
    return str(session.session_id)


async def test_comment_registers_all_primitives(server: MCPServer) -> None:
    """The comment context exposes its tools, resources and prompts."""
    tools = {tool.name for tool in await list_tools(server)}
    templates = {template.uri_template for template in await list_resource_templates(server)}
    prompts = {prompt.name for prompt in await list_prompts(server)}

    assert tools >= COMMENT_TOOLS
    assert templates >= COMMENT_TEMPLATES
    assert prompts >= COMMENT_PROMPTS


async def test_comment_tool_hints(server: MCPServer) -> None:
    """The parameterised reads and the destructive commands carry their hints."""
    by_name = {tool.name: tool for tool in await list_tools(server)}

    assert by_name["list_threads"].annotations.read_only_hint is True
    assert by_name["get_thread"].annotations.read_only_hint is True
    assert by_name["list_comments"].annotations.read_only_hint is True
    assert by_name["discard_thread"].annotations.destructive_hint is True
    assert by_name["discard_comment"].annotations.destructive_hint is True


async def test_comment_workflow_over_mcp(server: MCPServer, container: Container) -> None:
    """A thread and a reply round-trip through the tools and resources."""
    await create_session(container)
    target = str(uuid4())

    created = await call_tool(
        server,
        "create_thread",
        {
            "target_type": "table",
            "target_id": target,
            "body": "root body",
            "title": "pricing",
        },
    )
    thread_id = created.structured_content["thread_id"]
    root_id = created.structured_content["root_comment_id"]

    reply = await call_tool(
        server,
        "add_comment",
        {
            "thread_id": thread_id,
            "body": "first reply",
            "parent_comment_id": root_id,
        },
    )
    assert reply.structured_content["depth"] == 1
    assert reply.structured_content["depth_warning"] is None

    async def comments_ready() -> bool:
        payload = await read_resource(server, f"comment:///threads/{thread_id}/comments")
        return len(payload) == 2

    await wait_for(comments_ready)

    detail = await call_tool(server, "get_thread", {"thread_id": thread_id})
    assert detail.structured_content["thread"]["thread_id"] == thread_id
    assert detail.structured_content["thread"]["title"] == "pricing"
    assert [row["depth"] for row in detail.structured_content["comments"]] == [0, 1]

    flattened = await call_tool(
        server,
        "list_comments",
        {"thread_id": thread_id, "flatten_after": 0},
    )
    assert [row["depth"] for row in flattened.structured_content["result"]] == [0, 0]

    listed = await call_tool(
        server,
        "list_threads",
        {"target_type": "table", "target_id": target},
    )
    assert [row["thread_id"] for row in listed.structured_content["result"]] == [thread_id]

    targets = await read_resource(
        server,
        f"comment:///targets/table/{target}/threads",
    )
    assert [row["thread_id"] for row in targets] == [thread_id]


async def test_comment_tool_errors(server: MCPServer, container: Container) -> None:
    """Domain failures keep their bracketed category."""
    await create_session(container)

    unregistered = await call_tool(
        server,
        "create_thread",
        {
            "target_type": "diagram",
            "target_id": str(uuid4()),
            "body": "body",
        },
        raise_on_error=False,
    )
    assert "[not_found]" in unregistered.content[0].text

    unknown_thread = await call_tool(
        server,
        "get_thread",
        {"thread_id": str(uuid4())},
        raise_on_error=False,
    )
    assert "[not_found]" in unknown_thread.content[0].text
