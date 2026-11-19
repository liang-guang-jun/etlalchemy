"""Tests of the in-process MCP connector the agent uses by default."""

from __future__ import annotations

from uuid import uuid4

from etlalchemy.agent.mcp.client import McpClient
from etlalchemy.app.bootstrap import Container
from etlalchemy.app.mcp.inprocess import InProcessConnector
from etlalchemy.app.mcp.server import MCPServer
from etlalchemy.app.mcp.session import bind_session, context_session_id

from tests.app.mcp.support import sign_in


async def test_the_connector_lists_tools_without_http(server: MCPServer) -> None:
    """The agent reaches the very same tools without opening a socket."""
    client = McpClient(InProcessConnector(server.mcp))

    async with client.lifespan():
        tools = {tool.name for tool in await client.list_tools()}

    assert {"create_catalog", "list_conversations"} <= tools
    assert client.endpoint == "in-process"


async def test_a_tool_runs_as_the_bound_session(
    container: Container,
    server: MCPServer,
) -> None:
    """The caller behind the request is the identity the tool acts as.

    No bearer token travels: the route already verified it, so the connector
    binds the session and the tools read it like a token claim. The resolver is
    deliberately left alone here, so only the binding can supply the caller.
    """
    _, session = await sign_in(
        container,
        "connector@example.com",
        bind_resolver=False,
    )
    client = McpClient(InProcessConnector(server.mcp, session_id=session.session_id))

    async with client.lifespan():
        result = await client.call_tool("list_conversations", {})

    assert result.is_error is False


async def test_a_tool_without_a_session_fails_closed(server: MCPServer) -> None:
    """A run without a bound session cannot act as anybody."""
    client = McpClient(InProcessConnector(server.mcp))

    result = await client.call_tool("list_conversations", {})

    assert result.is_error is True


async def test_the_binding_does_not_leak_into_the_next_run(
    container: Container,
    server: MCPServer,
) -> None:
    """The caller of one run is invisible to the next one."""
    _, session = await sign_in(
        container,
        "connector@example.com",
        bind_resolver=False,
    )
    bound = McpClient(InProcessConnector(server.mcp, session_id=session.session_id))
    async with bound.lifespan():
        allowed = await bound.call_tool("list_conversations", {})

    anonymous = McpClient(InProcessConnector(server.mcp))
    async with anonymous.lifespan():
        rejected = await anonymous.call_tool("list_conversations", {})

    assert allowed.is_error is False
    assert rejected.is_error is True


def test_bind_session_restores_the_previous_caller() -> None:
    """The binding is scoped, so a nested call cannot inherit a caller."""
    session_id = uuid4()

    with bind_session(session_id):
        assert context_session_id() == session_id

    assert context_session_id() is None


async def test_the_http_app_serves_the_same_server(container: Container) -> None:
    """One FastMCP instance backs both ``/mcp`` and the in-process transport.

    Building a second server would register every tool twice and let the two
    paths drift apart, so the container owns the only instance.
    """
    from etlalchemy.app.api.app import create_app

    app = create_app(container)

    assert app.mcp_server is container.mcp_server()  # type: ignore[attr-defined]
    assert container.mcp_server() is container.mcp_server()
