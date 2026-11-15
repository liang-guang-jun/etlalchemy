"""Tests for the bearer authentication of the MCP delivery layer."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import httpx2
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport
from mcp.shared.exceptions import MCPError

from etlalchemy.app.auth import AuthSession, InvalidTokenError
from etlalchemy.app.bootstrap import Container
from etlalchemy.app.mcp.auth import IamTokenVerifier
from etlalchemy.app.mcp.server import MCPServer
from etlalchemy.iam.aggregates.types import Permission

MCP_PATH = "/mcp"
PASSWORD = "correct-horse-battery"
WAIT_TIMEOUT = 10.0


def _asgi_client(app: Any, token: str | None) -> Client:
    """Returns an MCP client that drives the ASGI app in process."""

    def factory(**kwargs: Any) -> httpx2.AsyncClient:
        return httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=app),
            base_url="http://testserver",
            **kwargs,
        )

    headers = {"Authorization": f"Bearer {token}"} if token is not None else None
    return Client(
        StreamableHttpTransport(
            "http://testserver" + MCP_PATH,
            headers=headers,
            httpx_client_factory=factory,
        ),
    )


async def _session_token(container: Container) -> str:
    """Creates a system administrator, logs it in and returns its bearer token."""
    iam = container.iam_application()
    await iam.bootstrap_admin("root@example.com", PASSWORD)

    async def identity_ready() -> bool:
        row = await container.iam_view().find_password_identity("root@example.com")
        return row is not None and await container.iam_view().get_password_hash(row.identity_id) is not None

    await wait_for(identity_ready)
    session = await iam.authenticate_password("root@example.com", PASSWORD)

    async def session_ready() -> bool:
        return await container.iam_view().get_session(session.session_id) is not None

    await wait_for(session_ready)
    return f"iam_sess_{session.session_id}"


class FakeAuthenticator:
    """Stand-in for ``SessionAuthenticator`` returning one configured session."""

    def __init__(self, session: Any | None, error: Exception | None = None) -> None:
        self.session = session
        self.error = error

    async def authenticate(self, raw_token: str) -> Any:
        """Returns the configured session or raises the configured error."""
        if self.error is not None:
            raise self.error
        return self.session


def build_session() -> AuthSession:
    """Returns an ``AuthSession`` carrying one catalog permission."""
    return AuthSession(
        session_id=uuid4(),
        user_id=uuid4(),
        identity_id=uuid4(),
        tenant_id=None,
        expires_at=datetime.now(UTC) + timedelta(hours=1),
        is_system_admin=False,
        permissions=frozenset({Permission(resource="catalog", action="write")}),
    )


async def test_verify_token_exposes_the_session_and_scopes() -> None:
    """A verified token carries the session id and the live permissions."""
    session = build_session()
    verifier = IamTokenVerifier(FakeAuthenticator(session))  # type: ignore[arg-type]

    access = await verifier.verify_token("iam_sess_" + str(session.session_id))

    assert access is not None
    assert access.client_id == str(session.user_id)
    assert access.scopes == ["catalog:write"]
    assert access.claims is not None
    assert access.claims["session_id"] == str(session.session_id)
    assert access.claims["is_system_admin"] is False


async def test_verify_token_rejects_an_unusable_token() -> None:
    """An invalid token returns ``None`` so FastMCP answers 401."""
    verifier = IamTokenVerifier(  # type: ignore[arg-type]
        FakeAuthenticator(None, InvalidTokenError("invalid or expired token")),
    )

    assert await verifier.verify_token("iam_sess_" + str(uuid4())) is None


async def test_server_installs_the_verifier_when_auth_is_required(
    container: Container,
) -> None:
    """The MCP server verifies bearer tokens unless authentication is disabled."""
    assert MCPServer(container, require_auth=True).mcp.auth is not None
    assert MCPServer(container, require_auth=False).mcp.auth is None


def test_mcp_endpoint_rejects_an_unauthenticated_request(
    container: Container,
) -> None:
    """Without a bearer token the mount answers 401 before any tool runs."""
    server = MCPServer(container, require_auth=True)
    app = FastAPI()
    app.router.routes.extend(server.mcp.http_app(path=MCP_PATH).routes)

    with TestClient(app) as client:
        response = client.post(
            MCP_PATH,
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        )

    assert response.status_code == 401
    assert response.headers["www-authenticate"].startswith("Bearer")


async def test_verifier_accepts_a_real_session(container: Container) -> None:
    """A session issued by the IAM application verifies through the shared layer."""
    iam = container.iam_application()
    if await iam.bootstrap_status() is False:
        await iam.bootstrap_admin("root@example.com", PASSWORD)

    async def identity_ready() -> bool:
        row = await container.iam_view().find_password_identity("root@example.com")
        return row is not None and await container.iam_view().get_password_hash(row.identity_id) is not None

    await wait_for(identity_ready)
    session = await iam.authenticate_password("root@example.com", PASSWORD)

    async def session_ready() -> bool:
        return await container.iam_view().get_session(session.session_id) is not None

    await wait_for(session_ready)
    verifier = IamTokenVerifier(container.session_authenticator())

    access = await verifier.verify_token(f"iam_sess_{session.session_id}")

    assert access is not None
    assert access.claims is not None
    assert UUID(str(access.claims["session_id"])) == session.session_id
    assert access.scopes == ["*"]
    # SQLite returns naive datetimes; a naive expiry would be shifted by the local
    # UTC offset and FastMCP would reject the token as already expired.
    assert access.expires_at is not None
    assert access.expires_at > int(datetime.now(UTC).timestamp())


async def wait_for(predicate: Callable[[], Any], timeout: float = WAIT_TIMEOUT) -> Any:
    """Polls an async ``predicate`` until it returns a truthy value."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = await predicate()
        if result:
            return result
        await asyncio.sleep(0.05)
    raise AssertionError("timed out waiting for the projection")


async def test_unknown_session_is_not_verified(container: Container) -> None:
    """A token naming a missing session never verifies."""
    verifier = IamTokenVerifier(container.session_authenticator())

    assert await verifier.verify_token(f"iam_sess_{uuid4()}") is None


@pytest.mark.parametrize("token", ["", "iam_sess_", "iam_sess_not-a-uuid", str(uuid4())])
async def test_malformed_tokens_are_not_verified(container: Container, token: str) -> None:
    """Only ``iam_sess_<uuid>`` values reach the session store."""
    verifier = IamTokenVerifier(container.session_authenticator())

    assert await verifier.verify_token(token) is None


async def test_a_mounted_tool_does_not_run_without_a_token(container: Container) -> None:
    """The parent auth provider protects tools that live on a mounted sub-server."""
    server = MCPServer(container, require_auth=True)
    app = server.mcp.http_app(path=MCP_PATH)

    async with app.router.lifespan_context(app):
        with pytest.raises(MCPError):
            async with _asgi_client(app, None) as client:
                await client.call_tool("create_catalog", {"name": "unauthorized"})

    assert await container.catalog_view().list_catalogs() == []


async def test_a_mounted_tool_runs_with_a_valid_token(container: Container) -> None:
    """With a verified token the same mounted tool executes."""
    token = await _session_token(container)
    server = MCPServer(container, require_auth=True)
    app = server.mcp.http_app(path=MCP_PATH)

    async with app.router.lifespan_context(app):
        async with _asgi_client(app, token) as client:
            created = await client.call_tool("create_catalog", {"name": "authorized"})

    assert created.structured_content is not None
    wait_for_catalog = await wait_for(
        lambda: _catalog_names(container),
    )
    assert "authorized" in wait_for_catalog


async def _catalog_names(container: Container) -> list[str]:
    """Returns the projected catalog names."""
    return [row.name for row in await container.catalog_view().list_catalogs()]


async def test_only_the_parent_server_carries_the_auth_provider(
    container: Container,
) -> None:
    """Mounted sub-servers have no provider of their own; only the parent app is served."""
    server = MCPServer(container, require_auth=True)

    assert server.mcp.auth is not None
    assert all(context.auth is None for context in server.contexts)
