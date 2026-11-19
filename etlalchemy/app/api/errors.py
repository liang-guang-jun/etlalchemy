"""HTTP error mapping shared by the delivery layer's route modules.

Every route module maps its context's errors onto the same status codes: a
rejected write is 409, an unknown reference is 404, a malformed command is 400
and an IAM rejection is 401 or 403. Seven modules used to spell that out with
their own ``_error_handler`` factory and five ``for`` loops; the mapping is a
table, so it lives here.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING, Any

from fastapi.responses import JSONResponse

if TYPE_CHECKING:
    from fastapi import FastAPI, Request

__all__ = ["error_handler", "install_error_handlers", "install_exception_handlers"]

CONFLICT = 409
"""Status of a command the aggregate rejected."""

NOT_FOUND = 404
"""Status of a reference that does not resolve."""

BAD_REQUEST = 400
"""Status of a malformed or empty command."""

UNAUTHORIZED = 401
"""Status of a missing, revoked or expired session."""

FORBIDDEN = 403
"""Status of a session that lacks the required permission."""


def error_handler(status_code: int) -> Any:
    """Builds a handler that renders the error message with the given status.

    Args:
        status_code: Status returned for the mapped exception.

    Returns:
        An async FastAPI exception handler.
    """

    async def handler(request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(status_code=status_code, content={"detail": str(exc)})

    return handler


def install_error_handlers(
    app: FastAPI,
    status_code: int,
    errors: Iterable[type[Exception]],
) -> None:
    """Registers one status code for a group of exception types.

    Args:
        app: Application to register the handlers on.
        status_code: Status returned for every type in ``errors``.
        errors: Exception types mapped to that status.
    """
    handler = error_handler(status_code)
    for error in errors:
        app.add_exception_handler(error, handler)


def install_exception_handlers(
    app: FastAPI,
    *,
    conflict: Iterable[type[Exception]] = (),
    not_found: Iterable[type[Exception]] = (),
    bad_request: Iterable[type[Exception]] = (),
    unauthorized: Iterable[type[Exception]] = (),
    forbidden: Iterable[type[Exception]] = (),
) -> None:
    """Maps a context's error groups onto their HTTP status codes.

    Args:
        app: Application to register the handlers on.
        conflict: Errors answered with 409.
        not_found: Errors answered with 404.
        bad_request: Errors answered with 400.
        unauthorized: Errors answered with 401.
        forbidden: Errors answered with 403.
    """
    install_error_handlers(app, CONFLICT, conflict)
    install_error_handlers(app, NOT_FOUND, not_found)
    install_error_handlers(app, BAD_REQUEST, bad_request)
    install_error_handlers(app, UNAUTHORIZED, unauthorized)
    install_error_handlers(app, FORBIDDEN, forbidden)
