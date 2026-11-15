"""MCP connector that calls the server of this process directly.

The agent normally reaches ``/mcp`` over streamable HTTP. In a single-process
deployment that round trip only adds failure modes: the configured
``agent.mcp_url`` must match the port the server actually listens on, the
call needs a bearer token, and any ``HTTP_PROXY``/``ALL_PROXY`` in the
environment may intercept it.

This connector skips all of that. It hands FastMCP's own in-memory client the
mounted server object, so a tool call is the same coroutine as an HTTP call —
still passing through the context packages, the tool registry, the annotations
and every permission check of the applications — without a socket.

Authentication stays explicit: the route already verified the bearer token, so
the session id travels in the context (see :mod:`etlalchemy.app.mcp.session`)
and tools read it like a token claim.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager
from datetime import timedelta
from typing import Any
from uuid import UUID

from fastmcp import Client, FastMCP
from mcp import ClientSession

from etlalchemy.app.mcp.session import pop_session, push_session
from etlalchemy.shared.logging import get_logger

DESCRIPTION = "in-process"
"""Description the agent reports for this connector."""


class InProcessConnector:
    """Opens MCP sessions against the server object of this process."""

    def __init__(
        self,
        server: FastMCP,
        *,
        session_id: UUID | None = None,
    ) -> None:
        """Stores the server and the caller the sessions act as.

        Args:
            server: Mounted FastMCP server, usually ``MCPServer.mcp``.
            session_id: Verified session of the caller, or ``None`` for a run
                without one (tools that need a caller then fail closed).
        """
        self._server = server
        self._session_id = session_id
        self._log = get_logger("agent.mcp.in_process")

    @property
    def description(self) -> str:
        """Returns the transport name reported in logs and errors."""
        return DESCRIPTION

    async def connect(self, timeout_seconds: float) -> tuple[AsyncExitStack, ClientSession]:
        """Opens an in-memory session bound to the caller's session.

        Args:
            timeout_seconds: Timeout of one MCP request.

        Returns:
            The session, plus the stack that unbinds the caller and closes the
            client.
        """
        stack = AsyncExitStack()
        token = push_session(self._session_id)
        stack.callback(pop_session, token)
        try:
            client = await stack.enter_async_context(
                self._client(timedelta(seconds=timeout_seconds)),
            )
        except Exception:
            # Release the binding again: the client retries the connection, and
            # a leaked caller would outlive this attempt.
            await stack.aclose()
            raise
        self._log.debug("agent.mcp.in_process.connected", has_session=self._session_id is not None)
        return stack, client.session

    @asynccontextmanager
    async def _client(self, timeout: timedelta) -> AsyncIterator[Client[Any]]:
        """Yields the FastMCP client of one session.

        Kept in a helper so the type of ``Client`` stays out of the public
        signature of :meth:`connect`.

        Args:
            timeout: Timeout of one request.

        Yields:
            The connected client.
        """
        async with Client(self._server, timeout=timeout) as client:
            yield client
