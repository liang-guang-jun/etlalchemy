"""Tests of the shared HTTP error mapping."""

from __future__ import annotations

from typing import Any

import pytest
from etlalchemy.app.api.errors import (
    error_handler,
    install_error_handlers,
    install_exception_handlers,
)
from fastapi import FastAPI
from fastapi.testclient import TestClient


class _ConflictError(Exception):
    """Stands in for a rejected write."""


class _MissingError(Exception):
    """Stands in for an unknown reference."""


class _MalformedError(Exception):
    """Stands in for a malformed command."""


def _app(**groups: Any) -> FastAPI:
    app = FastAPI()
    install_exception_handlers(app, **groups)
    return app


def test_every_group_maps_to_its_status() -> None:
    """Each keyword maps its exceptions onto the matching status code."""
    app = _app(
        conflict=(_ConflictError,),
        not_found=(_MissingError,),
        bad_request=(_MalformedError,),
    )

    @app.get("/conflict")
    async def conflict() -> None:
        raise _ConflictError("taken")

    @app.get("/missing")
    async def missing() -> None:
        raise _MissingError("unknown")

    @app.get("/malformed")
    async def malformed() -> None:
        raise _MalformedError("bad")

    client = TestClient(app)
    assert client.get("/conflict").status_code == 409
    assert client.get("/missing").status_code == 404
    assert client.get("/malformed").status_code == 400


def test_the_message_becomes_the_detail() -> None:
    """The rendered body keeps the exception message, like every route did."""
    app = _app(not_found=(_MissingError,))

    @app.get("/missing")
    async def missing() -> None:
        raise _MissingError("schema 'x' does not exist")

    response = TestClient(app).get("/missing")

    assert response.json() == {"detail": "schema 'x' does not exist"}


def test_unauthorized_and_forbidden_are_distinct() -> None:
    """A missing session is 401 while a denied one is 403."""

    class _Unauthenticated(Exception):
        """Stands in for a rejected token."""

    class _Denied(Exception):
        """Stands in for a missing permission."""

    app = _app(unauthorized=(_Unauthenticated,), forbidden=(_Denied,))

    @app.get("/unauthorized")
    async def unauthorized() -> None:
        raise _Unauthenticated("no session")

    @app.get("/forbidden")
    async def forbidden() -> None:
        raise _Denied("not allowed")

    client = TestClient(app)
    assert client.get("/unauthorized").status_code == 401
    assert client.get("/forbidden").status_code == 403


def test_install_error_handlers_registers_one_group() -> None:
    """The single-group helper registers every type it is given."""
    app = FastAPI()
    install_error_handlers(app, 418, [_ConflictError, _MissingError])

    assert _ConflictError in app.exception_handlers
    assert _MissingError in app.exception_handlers


def test_error_handler_keeps_the_exception_message() -> None:
    """The handler factory is the building block the groups share."""
    handler = error_handler(409)
    assert callable(handler)


@pytest.mark.parametrize(
    ("status", "expected"),
    [(409, 409), (404, 404), (400, 400), (401, 401), (403, 403)],
)
def test_error_handler_renders_the_requested_status(status: int, expected: int) -> None:
    """The built handler answers with the status it was created for."""
    app = FastAPI()
    app.add_exception_handler(_ConflictError, error_handler(status))

    @app.get("/boom")
    async def boom() -> None:
        raise _ConflictError("boom")

    assert TestClient(app).get("/boom").status_code == expected
