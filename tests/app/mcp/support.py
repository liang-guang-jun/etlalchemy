"""Helpers that drive the MCP server through an in-memory client session."""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Callable
from typing import Any

from dependency_injector import providers
from fastmcp import Client

from etlalchemy.app.bootstrap import Container
from etlalchemy.app.mcp.server import MCPServer


async def list_tools(server: MCPServer) -> list[Any]:
    """Returns the tools the server exposes."""
    async with Client(server.mcp) as client:
        return await client.list_tools()


async def list_resources(server: MCPServer) -> list[Any]:
    """Returns the static resources the server exposes."""
    async with Client(server.mcp) as client:
        return await client.list_resources()


async def list_resource_templates(server: MCPServer) -> list[Any]:
    """Returns the resource templates the server exposes."""
    async with Client(server.mcp) as client:
        return await client.list_resource_templates()


async def list_prompts(server: MCPServer) -> list[Any]:
    """Returns the prompts the server exposes."""
    async with Client(server.mcp) as client:
        return await client.list_prompts()


async def call_tool(
    server: MCPServer,
    name: str,
    arguments: dict[str, Any] | None = None,
    *,
    raise_on_error: bool = True,
) -> Any:
    """Calls a tool and returns the raw result."""
    async with Client(server.mcp) as client:
        return await client.call_tool(name, arguments, raise_on_error=raise_on_error)


async def read_resource(server: MCPServer, uri: str) -> Any:
    """Reads a resource and returns its decoded JSON payload."""
    async with Client(server.mcp) as client:
        contents = await client.read_resource(uri)
        return json.loads(contents[0].text)  # type: ignore[union-attr]


async def get_prompt(
    server: MCPServer,
    name: str,
    arguments: dict[str, Any] | None = None,
) -> Any:
    """Returns the rendered messages of a prompt."""
    async with Client(server.mcp) as client:
        return await client.get_prompt(name, arguments)


PASSWORD = "correct-horse-battery"
"""Password of the administrator the helpers below create."""

WAIT_TIMEOUT = 10.0
"""Seconds the helpers wait for the read model to catch up."""


async def wait_for(predicate: Callable[[], Any], timeout: float = WAIT_TIMEOUT) -> Any:
    """Polls ``predicate`` until it returns a truthy value."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = await predicate()
        if result:
            return result
        await asyncio.sleep(0.05)
    raise AssertionError("timed out waiting for the projection")


async def sign_in(
    container: Container,
    email: str,
    *,
    bind_resolver: bool = True,
) -> tuple[str, Any]:
    """Bootstraps an administrator and logs it in.

    Args:
        container: Container whose IAM application and view are used.
        email: Login of the administrator; bootstrap must not have run yet.
        bind_resolver: Also point ``mcp_session_resolver`` at the new session,
            so a plain in-memory client can call parameterised tools. Turn it
            off to prove that a connector carries the caller itself.

    Returns:
        The session id as text, and the session.
    """
    iam = container.iam_application()
    await iam.bootstrap_admin(email, PASSWORD)

    async def identity_ready() -> bool:
        row = await container.iam_view().find_password_identity(email)
        return row is not None and (
            await container.iam_view().get_password_hash(row.identity_id) is not None
        )

    await wait_for(identity_ready)
    session = await iam.authenticate_password(email, PASSWORD)

    async def session_ready() -> bool:
        return await container.iam_view().get_session(session.session_id) is not None

    await wait_for(session_ready)
    if bind_resolver:
        container.mcp_session_resolver.override(providers.Object(session.session_id))
    return str(session.session_id), session
