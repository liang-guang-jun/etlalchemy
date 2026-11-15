"""Import-time registry of MCP context factories.

A context package decorates one registration function with :func:`mcp_context`.
The decorator only appends to a module-private list, so importing a context has
no server or container side effect and the order in which packages are imported
decides the order in which their servers are built. Everything else is deferred
to :func:`build_contexts`.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Final

from fastmcp import FastMCP

if TYPE_CHECKING:
    from etlalchemy.app.bootstrap import Container

ContextRegisterFn = Callable[[FastMCP, "Container"], None]
"""Registers one context's primitives on a server of its own."""

ContextFactory = tuple[str, str, ContextRegisterFn]
"""The ``(name, instructions, register)`` triple of one registered context."""

_FACTORIES: Final[list[ContextFactory]] = []

__all__ = [
    "ContextFactory",
    "ContextRegisterFn",
    "build_contexts",
    "contexts",
    "mcp_context",
]


def mcp_context(
    name: str,
    instructions: str = "",
) -> Callable[[ContextRegisterFn], ContextRegisterFn]:
    """Marks a registration function as the factory of one MCP context.

    The decorated function is returned unchanged; only the ``(name, instructions,
    register)`` triple is recorded, so importing a context never builds a server.

    Args:
        name: Context name, also the name of the mounted server.
        instructions: Description the context would advertise when run alone.

    Returns:
        A decorator that registers the function and returns it untouched.

    Raises:
        ValueError: If another context already registered the same name.
    """

    def decorator(register: ContextRegisterFn) -> ContextRegisterFn:
        """Records the factory and returns the function unchanged."""
        if any(registered[0] == name for registered in _FACTORIES):
            raise ValueError(f"duplicate MCP context name: {name!r}")
        _FACTORIES.append((name, instructions, register))
        return register

    return decorator


def contexts() -> tuple[ContextFactory, ...]:
    """Returns the registered factories in registration order."""
    return tuple(_FACTORIES)


def build_contexts(container: Container) -> list[FastMCP]:
    """Builds one populated server per registered context.

    Args:
        container: Container the contexts resolve their applications from.

    Returns:
        The servers, in registration order, ready to be mounted on a parent.
    """
    servers: list[FastMCP] = []
    for name, instructions, register in _FACTORIES:
        server: FastMCP = FastMCP(name, instructions=instructions or None)
        register(server, container)
        servers.append(server)
    return servers
