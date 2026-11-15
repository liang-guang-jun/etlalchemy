"""Async client for the ETLAlchemy MCP endpoint.

The agent talks to the MCP server exactly like any other client: it lists
tools, resources and prompts, reads resources, renders prompts and calls tools.
No part of the server is imported, so a new bounded context is discovered
automatically once `app/mcp/server.py` imports it.

*How* the session reaches the server is a connector (see :class:`McpConnector`):
:class:`HttpConnector` speaks streamable HTTP, and the assembly layer adds an
in-process connector that reuses the server object of this process.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Mapping
from contextlib import AsyncExitStack, asynccontextmanager
from typing import Any, Protocol, runtime_checkable

import httpx2
from mcp import ClientSession
from mcp.client import streamable_http as streamable
from mcp.types import (
    CallToolResult,
    GetPromptResult,
    ListPromptsResult,
    ListResourcesResult,
    ListToolsResult,
    Prompt,
    ReadResourceResult,
    Resource,
    ResourceTemplate,
    Tool,
)

from etlalchemy.agent.errors import McpConnectionError
from etlalchemy.shared.logging import get_logger

BACKOFF_SECONDS = (1.0, 2.0, 4.0)
"""Delay before each reconnect attempt."""


def build_http_client(
    *,
    headers: Mapping[str, str] | None,
    timeout_seconds: float,
) -> httpx2.AsyncClient:
    """Builds the HTTP client of one MCP connection.

    The endpoint is the process's own server, so ambient proxy variables are
    ignored: a container that exports ``ALL_PROXY=socks5://…`` (or an
    ``HTTP_PROXY`` that does not list the host in ``NO_PROXY``) would otherwise
    push the internal call through a proxy that cannot reach it.

    Args:
        headers: Headers sent with every request, usually the bearer token.
        timeout_seconds: Per-request timeout.

    Returns:
        A client that never reads proxy or CA settings from the environment.
    """
    return httpx2.AsyncClient(
        headers=dict(headers) if headers else None,
        timeout=httpx2.Timeout(timeout_seconds),
        trust_env=False,
    )


@runtime_checkable
class McpConnector(Protocol):
    """Opens MCP client sessions for one caller."""

    @property
    def description(self) -> str:
        """Returns a short name of the transport, used in logs and errors."""
        ...

    async def connect(self, timeout_seconds: float) -> tuple[AsyncExitStack, ClientSession]:
        """Opens one session and returns it with the stack that owns it.

        Args:
            timeout_seconds: Timeout of one request.

        Returns:
            The session, plus the stack that released everything it opened.
        """
        ...


class HttpConnector:
    """Connects to an MCP endpoint over streamable HTTP."""

    def __init__(self, url: str, *, headers: Mapping[str, str] | None = None) -> None:
        """Stores the endpoint and the headers sent with every request.

        Args:
            url: Streamable HTTP endpoint of the MCP server.
            headers: Headers, normally the caller's bearer token.
        """
        self._url = url
        self._headers = dict(headers or {})

    @property
    def description(self) -> str:
        """Returns the endpoint URL."""
        return self._url

    async def connect(self, timeout_seconds: float) -> tuple[AsyncExitStack, ClientSession]:
        """Opens an HTTP session and initialises the MCP handshake."""
        stack = AsyncExitStack()
        try:
            http_client = await stack.enter_async_context(
                build_http_client(
                    headers=self._headers,
                    timeout_seconds=timeout_seconds,
                )
            )
            read, write = await stack.enter_async_context(
                streamable.streamable_http_client(self._url, http_client=http_client)
            )
            session = await stack.enter_async_context(ClientSession(read, write))
            await session.initialize()
        except Exception:
            await stack.aclose()
            raise
        return stack, session


class McpClient:
    """Short lived, authenticated sessions against one MCP server."""

    def __init__(
        self,
        connector: McpConnector,
        *,
        request_timeout_seconds: float = 30.0,
        connect_retries: int = 3,
    ) -> None:
        """Stores the connector, the request timeout and the retry budget.

        Args:
            connector: Transport that opens the sessions.
            request_timeout_seconds: Timeout of one MCP request.
            connect_retries: Extra attempts after the first failure.
        """
        self._connector = connector
        self._timeout = request_timeout_seconds
        self._retries = max(0, connect_retries)
        self._shared: ClientSession | None = None
        self._log = get_logger("agent.mcp")

    @property
    def endpoint(self) -> str:
        """Returns a short description of the transport, for logs and errors."""
        return self._connector.description

    @asynccontextmanager
    async def lifespan(self) -> AsyncIterator[ClientSession]:
        """Reuses one MCP session for the whole block.

        A run makes dozens of requests; reconnecting for each of them pays the
        handshake again and again. Every ``session()`` inside the block yields the
        same connection.

        Yields:
            The shared session.

        Raises:
            McpConnectionError: If the connection cannot be established.
        """
        stack, session = await self._open()
        previous = self._shared
        self._shared = session
        try:
            yield session
        finally:
            self._shared = previous
            await stack.aclose()

    @asynccontextmanager
    async def session(self) -> AsyncIterator[ClientSession]:
        """Opens an initialised MCP session with the configured retry policy.

        Inside :meth:`lifespan` the shared session is reused instead of opening
        a new one.

        Yields:
            The session, ready for requests.

        Raises:
            McpConnectionError: If every connection attempt fails.
        """
        if self._shared is not None:
            yield self._shared
            return
        stack, session = await self._open()
        try:
            yield session
        finally:
            await stack.aclose()

    async def _open(self) -> tuple[AsyncExitStack, ClientSession]:
        """Connects and initialises a session, retrying with exponential backoff."""
        last: Exception | None = None
        for attempt in range(self._retries + 1):
            try:
                return await self._connector.connect(self._timeout)
            except Exception as exc:
                last = exc
                delay = BACKOFF_SECONDS[min(attempt, len(BACKOFF_SECONDS) - 1)]
                self._log.warning(
                    "agent.mcp.connect.failed",
                    endpoint=self._connector.description,
                    attempt=attempt + 1,
                    error=str(exc),
                )
                await asyncio.sleep(delay)
                continue
        msg = f"cannot connect to the MCP endpoint {self._connector.description!r}"
        raise McpConnectionError(msg) from last

    async def list_tools(self) -> list[Tool]:
        """Returns every tool the MCP server advertises."""
        async with self.session() as session:
            result: ListToolsResult = await session.list_tools()
            return list(result.tools)

    async def list_resources(self) -> list[Resource]:
        """Returns every static resource the MCP server advertises."""
        async with self.session() as session:
            result: ListResourcesResult = await session.list_resources()
            return list(result.resources)

    async def list_resource_templates(self) -> list[ResourceTemplate]:
        """Returns every resource template the MCP server advertises."""
        async with self.session() as session:
            result = await session.list_resource_templates()
            return list(result.resource_templates)

    async def list_prompts(self) -> list[Prompt]:
        """Returns every prompt the MCP server advertises."""
        async with self.session() as session:
            result: ListPromptsResult = await session.list_prompts()
            return list(result.prompts)

    async def read_resource(self, uri: str) -> ReadResourceResult:
        """Reads one resource by URI."""
        async with self.session() as session:
            result: ReadResourceResult = await session.read_resource(uri)
            return result

    async def get_prompt(
        self,
        name: str,
        arguments: Mapping[str, str] | None = None,
    ) -> GetPromptResult:
        """Renders one server-side prompt."""
        async with self.session() as session:
            result: GetPromptResult = await session.get_prompt(
                name,
                dict(arguments or {}) or None,
            )
            return result

    async def call_tool(
        self,
        name: str,
        arguments: Mapping[str, Any],
        *,
        timeout_seconds: float | None = None,
    ) -> CallToolResult:
        """Calls one tool and returns its raw MCP result."""
        async with self.session() as session:
            call = session.call_tool(name, dict(arguments))
            if timeout_seconds is None:
                result: CallToolResult = await call
            else:
                result = await asyncio.wait_for(call, timeout=timeout_seconds)
            return result

    async def server_info(self) -> dict[str, Any]:
        """Returns the `initialize` result advertised by the server."""
        async with self.session() as session:
            info = session.server_info
            return {
                "name": getattr(info, "name", None),
                "version": getattr(info, "version", None),
                "protocol_version": session.protocol_version,
            }
