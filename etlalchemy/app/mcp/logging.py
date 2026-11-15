"""FastMCP middleware that logs the primitives a client calls.

Mounted context servers forward their calls through the parent, so installing
the middleware once on the parent covers every context.
"""

from __future__ import annotations

import time
from typing import Any

from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext

from etlalchemy.shared.logging import bound_context, get_logger

LOGGER_NAME = "etlalchemy.mcp"
"""Logger that carries the per-call line."""


class McpCallLoggingMiddleware(Middleware):
    """Logs tool calls, resource reads and prompt renders with their duration."""

    async def on_call_tool(
        self,
        context: MiddlewareContext[Any],
        call_next: CallNext[Any, Any],
    ) -> Any:
        """Logs one tool call."""
        return await self._log_call(
            "mcp.tool",
            {"tool": context.message.name},
            context,
            call_next,
        )

    async def on_read_resource(
        self,
        context: MiddlewareContext[Any],
        call_next: CallNext[Any, Any],
    ) -> Any:
        """Logs one resource read."""
        return await self._log_call(
            "mcp.resource",
            {"resource": str(context.message.uri)},
            context,
            call_next,
        )

    async def on_get_prompt(
        self,
        context: MiddlewareContext[Any],
        call_next: CallNext[Any, Any],
    ) -> Any:
        """Logs one prompt render."""
        return await self._log_call(
            "mcp.prompt",
            {"prompt": context.message.name},
            context,
            call_next,
        )

    async def _log_call(
        self,
        event: str,
        fields: dict[str, Any],
        context: MiddlewareContext[Any],
        call_next: CallNext[Any, Any],
    ) -> Any:
        """Runs one MCP call, logging its duration or its failure."""
        log = get_logger(LOGGER_NAME)
        started = time.perf_counter()
        with bound_context(**fields):
            try:
                result = await call_next(context)
            except Exception:
                log.exception(
                    f"{event} failed",
                    duration_ms=int((time.perf_counter() - started) * 1000),
                    **fields,
                )
                raise
        log.info(event, duration_ms=int((time.perf_counter() - started) * 1000), **fields)
        return result
