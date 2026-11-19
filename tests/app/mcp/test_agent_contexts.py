"""Tests for the agent MCP contexts and the package boundary they rely on."""

from __future__ import annotations

import json
import pathlib
from typing import Any

from etlalchemy.app.bootstrap import Container
from etlalchemy.app.mcp.server import MCPServer

from tests.app.mcp.support import (
    call_tool,
    list_resource_templates,
    list_resources,
    list_tools,
    read_resource,
    sign_in,
    wait_for,
)

AGENT_TOOLS = {
    "list_llm_providers",
    "get_llm_provider",
    "list_conversations",
    "list_conversation_messages",
}


def payload(result: Any) -> Any:
    """Returns the JSON payload a tool answered with."""
    content = getattr(result, "content", None)
    if content:
        text = getattr(content[0], "text", None)
        if isinstance(text, str):
            return json.loads(text)
    data = result.data
    return data.root if hasattr(data, "root") else data


async def test_agent_contexts_register_their_primitives(server: MCPServer) -> None:
    """Both contexts register their tools, and only llm_config has resources."""
    tools = {tool.name for tool in await list_tools(server)}
    resources = {str(resource.uri) for resource in await list_resources(server)}
    templates = {template.uri_template for template in await list_resource_templates(server)}

    assert tools >= AGENT_TOOLS
    assert "llm:///providers" in resources
    assert "llm:///{provider_id}" in templates


async def test_agent_tools_are_read_only(server: MCPServer) -> None:
    """Every agent tool is a parameterised read."""
    by_name = {tool.name: tool for tool in await list_tools(server)}

    for name in AGENT_TOOLS:
        assert by_name[name].annotations.read_only_hint is True


async def test_list_llm_providers_only_shows_visible_providers(
    container: Container,
    server: MCPServer,
) -> None:
    """A provider owned by somebody else is not listed."""
    _, session = await sign_in(container, "root@example.com")
    llm = container.llm_config_application()
    mine = await llm.create_llm_provider(
        session.session_id,
        "mine",
        "openai",
        credential_ref="env:KEY",
    )
    public = await llm.create_llm_provider(
        session.session_id,
        "public",
        "openai",
        credential_ref="env:KEY",
        is_public=True,
    )

    async def projected() -> bool:
        return len(await container.llm_config_view().list_providers()) == 2

    await wait_for(projected)

    result = await call_tool(server, "list_llm_providers", {})
    names = {entry["name"] for entry in payload(result)}

    assert names == {"mine", "public"}
    assert {entry["provider_id"] for entry in payload(result)} == {str(mine), str(public)}


async def test_provider_resource_exposes_only_public_providers(
    container: Container,
    server: MCPServer,
) -> None:
    """A resource carries no caller, so it never leaks a private provider."""
    _, session = await sign_in(container, "root@example.com")
    llm = container.llm_config_application()
    private = await llm.create_llm_provider(
        session.session_id,
        "private",
        "openai",
        credential_ref="env:KEY",
    )
    public = await llm.create_llm_provider(
        session.session_id,
        "public",
        "openai",
        credential_ref="env:KEY",
        is_public=True,
    )

    async def projected() -> bool:
        return len(await container.llm_config_view().list_providers()) == 2

    await wait_for(projected)

    listed = await read_resource(server, "llm:///providers")
    assert [entry["provider_id"] for entry in listed] == [str(public)]
    assert await read_resource(server, f"llm:///{private}") is None


async def test_list_conversations_is_scoped_to_the_caller(
    container: Container,
    server: MCPServer,
) -> None:
    """The conversation tools return the caller's conversations only."""
    _, session = await sign_in(container, "root@example.com")
    conversations = container.conversation_application()
    conversation_id = await conversations.start_conversation(session.session_id, "mine")
    await conversations.append_user_message(session.session_id, conversation_id, "hello")

    async def projected() -> bool:
        return len(await container.conversation_view().list_conversations(session.user_id)) == 1

    await wait_for(projected)

    listed = await call_tool(server, "list_conversations", {})
    assert [entry["conversation_id"] for entry in payload(listed)] == [str(conversation_id)]

    messages = await call_tool(
        server,
        "list_conversation_messages",
        {"conversation_id": str(conversation_id)},
    )
    assert [entry["role"] for entry in payload(messages)] == ["user"]


def test_the_agent_package_does_not_import_fastmcp() -> None:
    """The delivery layer owns FastMCP; the runtime must stay transport agnostic."""
    agent_root = pathlib.Path("etlalchemy/agent")
    offenders = [
        path
        for path in agent_root.rglob("*.py")
        if "fastmcp" in path.read_text(encoding="utf-8")
    ]

    assert offenders == []


def test_the_agent_package_does_not_import_the_assembly_layer() -> None:
    """A bounded context and the runtime never depend on ``etlalchemy.app``."""
    agent_root = pathlib.Path("etlalchemy/agent")
    offenders = [
        path
        for path in agent_root.rglob("*.py")
        if "etlalchemy.app" in path.read_text(encoding="utf-8")
    ]

    assert offenders == []
