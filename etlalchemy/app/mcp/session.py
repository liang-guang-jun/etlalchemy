"""Caller identity of MCP calls that never travel over HTTP.

An HTTP MCP call proves who the caller is with a bearer token, and
:class:`~etlalchemy.app.mcp.auth.IamTokenVerifier` turns it into an
:class:`~fastmcp.server.auth.AccessToken`. An **in-process** call has no token:
the agent runs inside the already authenticated request, so the route hands the
verified session id over here instead, and every tool reads it exactly as it
reads a claim.

The binding is a :class:`~contextvars.ContextVar`, so concurrent runs cannot see
each other's session: every run is its own asyncio task, and a task starts with
a copy of the context it was created in.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar, Token
from uuid import UUID

_CURRENT_SESSION: ContextVar[UUID | None] = ContextVar(
    "mcp_in_process_session",
    default=None,
)
"""Session of the in-process MCP caller, or ``None`` outside one."""


def push_session(session_id: UUID | None) -> Token[UUID | None]:
    """Binds a session to the current context.

    Args:
        session_id: Session of the caller, or ``None`` to bind nothing.

    Returns:
        The token to hand back to :func:`pop_session`.
    """
    return _CURRENT_SESSION.set(session_id)


def pop_session(token: Token[UUID | None]) -> None:
    """Restores the previous binding.

    Args:
        token: Token returned by :func:`push_session`.
    """
    _CURRENT_SESSION.reset(token)


@contextmanager
def bind_session(session_id: UUID) -> Iterator[None]:
    """Binds a session for the duration of the block.

    Args:
        session_id: Session of the caller.

    Yields:
        Nothing; the session is readable through :func:`context_session_id`.
    """
    token = push_session(session_id)
    try:
        yield
    finally:
        pop_session(token)


def context_session_id() -> UUID | None:
    """Returns the session bound to the current context, if any.

    Returns:
        The session id, or ``None`` when the call did not come from an
        in-process caller.
    """
    return _CURRENT_SESSION.get()
