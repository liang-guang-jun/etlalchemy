"""ASGI middleware that logs every request and binds its context.

A raw ASGI middleware is used on purpose: ``BaseHTTPMiddleware`` buffers streamed
responses, which would break the MCP endpoint that shares this application.
"""

from __future__ import annotations

import time
from typing import cast
from uuid import uuid4

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from etlalchemy.shared.logging import bound_context, get_logger

REQUEST_ID_HEADER = b"x-request-id"
"""Lowercase ASGI header name that carries the caller's request id."""

LOGGER_NAME = "etlalchemy.api"
"""Logger that carries the per-request access line."""


def _request_id(scope: Scope) -> str:
    """Returns the caller's request id, or a fresh one when absent.

    Args:
        scope: The ASGI connection scope.

    Returns:
        The header value if present and non-empty, otherwise a new UUID string.
    """
    for name, value in cast("list[tuple[bytes, bytes]]", scope["headers"]):
        if name.lower() == REQUEST_ID_HEADER:
            decoded = value.decode("latin-1").strip()
            if decoded:
                return decoded
    return str(uuid4())


class RequestLoggingMiddleware:
    """Logs one line per HTTP request and binds its context for the handlers.

    The line replaces ``uvicorn.access``, which ``logging.quiet`` silences by
    default, so reads served straight from a view still show up.
    """

    def __init__(self, app: ASGIApp) -> None:
        """Stores the wrapped application."""
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Binds the request context, echoes the request id and logs the outcome."""
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request_id = _request_id(scope)
        started = time.perf_counter()
        log = get_logger(LOGGER_NAME)

        async def send_with_request_id(message: Message) -> None:
            """Adds ``X-Request-ID`` and logs the response line once it starts."""
            if message["type"] == "http.response.start":
                MutableHeaders(scope=message).append("X-Request-ID", request_id)
                log.info(
                    "request",
                    status=message["status"],
                    duration_ms=int((time.perf_counter() - started) * 1000),
                )
            await send(message)

        with bound_context(
            request_id=request_id,
            method=scope["method"],
            path=scope["path"],
        ):
            try:
                await self.app(scope, receive, send_with_request_id)
            except Exception:
                log.exception(
                    "request failed",
                    duration_ms=int((time.perf_counter() - started) * 1000),
                )
                raise
