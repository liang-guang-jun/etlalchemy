"""Tests for the IAM HTTP routes."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient

from etlalchemy.app.api.app import create_app
from etlalchemy.app.bootstrap.factories import get_iam_env
from etlalchemy.app.bootstrap.settings import load_app_settings
from etlalchemy.iam.adapters.passwords import PasswordHasher
from etlalchemy.iam.aggregates.identity import Identity
from etlalchemy.iam.aggregates.user import User
from etlalchemy.iam.projection.projection import IamEventApplication

PASSWORD = "correct-horse-battery"
WAIT_TIMEOUT = 10.0


def wait_for(predicate: Callable[[], Any], timeout: float = WAIT_TIMEOUT) -> Any:
    """Polls ``predicate`` until it returns a truthy value."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = predicate()
        if result:
            return result
        time.sleep(0.05)
    raise AssertionError("timed out waiting for the projection")


def seed_admin(email: str) -> None:
    """Writes the first system administrator directly to the event store."""
    env = get_iam_env(load_app_settings())

    async def seed() -> None:
        async with IamEventApplication(env=env) as application:
            user = User(username=email, email=email, display_name=email)
            identity = Identity(user.id, "PASSWORD", "local", "Password")
            user.attach_identity(identity.id, "PASSWORD", "local")
            identity.change_password(PasswordHasher().hash(PASSWORD))
            user.grant_system_admin("bootstrap")
            await application.save(user, identity)

    asyncio.run(seed())


def login(client: TestClient, email: str, tenant_id: str | None = None) -> dict[str, str]:
    """Authenticates, waits for the session row and returns the bearer headers."""
    body: dict[str, Any] = {"login": email, "password": PASSWORD}
    if tenant_id is not None:
        body["tenant_id"] = tenant_id
    deadline = time.monotonic() + WAIT_TIMEOUT
    response = client.post("/iam/auth/password", json=body)
    while response.status_code != 200 and time.monotonic() < deadline:
        time.sleep(0.05)
        response = client.post("/iam/auth/password", json=body)
    assert response.status_code == 200, response.text
    headers = {"Authorization": f"Bearer {response.json()['access_token']}"}
    wait_for(
        lambda: client.get("/iam/sessions/current", headers=headers).status_code == 200,
    )
    return headers


def test_session_response_exposes_the_configured_refresh_lead(
    config_dir: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``refresh_at`` is the expiry minus ``iam.session_refresh_lead_minutes``."""
    monkeypatch.setenv("ETLALCHEMY_IAM__SESSION_REFRESH_LEAD_MINUTES", "7")
    seed_admin("lead@example.com")

    with TestClient(create_app()) as client:
        wait_for(lambda: client.get("/iam/bootstrap").json()["completed"])
        headers = login(client, "lead@example.com")
        current = client.get("/iam/sessions/current", headers=headers).json()

    expires_at = datetime.fromisoformat(current["expires_at"])
    refresh_at = datetime.fromisoformat(current["refresh_at"])
    assert expires_at - refresh_at == timedelta(minutes=7)


def test_login_bootstrap_and_authorize(config_dir: Any) -> None:
    """An administrator logs in and the sysadmin shortcut allows any action."""
    seed_admin("root@example.com")

    with TestClient(create_app()) as client:
        wait_for(lambda: client.get("/iam/bootstrap").json()["completed"])
        headers = login(client, "root@example.com")
        login_response = client.post(
            "/iam/auth/password",
            json={"login": "root@example.com", "password": PASSWORD},
        )
        assert login_response.json()["token_type"] == "bearer"
        assert login_response.json()["access_token"].startswith("iam_sess_")

        authorized = client.post(
            "/iam/authorize",
            json={"obj": "anything", "act": "read"},
            headers=headers,
        )
        assert authorized.status_code == 200
        assert authorized.json() == {"allowed": True}

        wrong = client.post(
            "/iam/auth/password",
            json={"login": "root@example.com", "password": "nope"},
        )
        assert wrong.status_code == 401


def test_tenant_and_member_routes(config_dir: Any) -> None:
    """A tenant is created, listed, renamed and filled with a member."""
    seed_admin("root@example.com")

    with TestClient(create_app()) as client:
        wait_for(lambda: client.get("/iam/bootstrap").json()["completed"])
        headers = login(client, "root@example.com")

        created = client.post(
            "/iam/tenants",
            json={"name": "acme", "description": "Acme"},
            headers=headers,
        )
        assert created.status_code == 201, created.text
        tenant_id = created.json()["tenant_id"]

        listed = wait_for(lambda: client.get("/iam/tenants", headers=headers).json())
        assert [tenant["name"] for tenant in listed] == ["acme"]

        user = client.post(
            "/iam/users",
            json={"username": "alice", "email": "alice@example.com"},
            headers=headers,
        )
        assert user.status_code == 201, user.text
        user_id = user.json()["user_id"]
        identity = client.post(
            f"/iam/users/{user_id}/identities/password",
            json={"password": PASSWORD},
            headers=headers,
        )
        assert identity.status_code == 201, identity.text

        added = client.post(
            f"/iam/tenants/{tenant_id}/members",
            json={"user_id": user_id},
            headers=headers,
        )
        assert added.status_code == 204, added.text

        members = wait_for(
            lambda: client.get(
                f"/iam/tenants/{tenant_id}/members",
                headers=headers,
            ).json(),
        )
        assert [member["username"] for member in members] == ["alice"]

        renamed = client.patch(
            f"/iam/tenants/{tenant_id}",
            json={"description": "Acme Corp"},
            headers=headers,
        )
        assert renamed.status_code == 204


def test_group_permission_is_enforced_over_http(config_dir: Any) -> None:
    """A member of a child group inherits the grants of its ancestor."""
    seed_admin("root@example.com")

    with TestClient(create_app()) as client:
        wait_for(lambda: client.get("/iam/bootstrap").json()["completed"])
        root_headers = login(client, "root@example.com")
        tenant_id = client.post(
            "/iam/tenants",
            json={"name": "acme"},
            headers=root_headers,
        ).json()["tenant_id"]
        user_id = client.post(
            "/iam/users",
            json={"username": "alice", "email": "alice@example.com"},
            headers=root_headers,
        ).json()["user_id"]
        client.post(
            f"/iam/users/{user_id}/identities/password",
            json={"password": PASSWORD},
            headers=root_headers,
        )
        client.post(
            f"/iam/tenants/{tenant_id}/members",
            json={"user_id": user_id},
            headers=root_headers,
        )
        parent_id = client.post(
            f"/iam/tenants/{tenant_id}/groups",
            json={"name": "analysts"},
            headers=root_headers,
        ).json()["group_id"]
        child_id = client.post(
            f"/iam/tenants/{tenant_id}/groups",
            json={"name": "reporting", "parent_group_id": parent_id},
            headers=root_headers,
        ).json()["group_id"]
        assert (
            client.post(
                f"/iam/tenants/{tenant_id}/groups/{parent_id}/permissions",
                json={"obj": "doc", "act": "read"},
                headers=root_headers,
            ).status_code
            == 204
        )
        assert (
            client.post(
                f"/iam/groups/{child_id}/members",
                json={"member_id": user_id},
                headers=root_headers,
            ).status_code
            == 204
        )

        headers = login(client, "alice", tenant_id)

        allowed = wait_for(
            lambda: client.post(
                "/iam/authorize",
                json={"obj": "doc", "act": "read"},
                headers=headers,
            ).json()["allowed"],
        )
        assert allowed is True
        denied = client.post(
            "/iam/authorize",
            json={"obj": "doc", "act": "write"},
            headers=headers,
        )
        assert denied.json() == {"allowed": False}


def test_missing_token_is_unauthorized(config_dir: Any) -> None:
    """A protected route rejects a request without a bearer token."""
    with TestClient(create_app()) as client:
        response = client.post("/iam/tenants", json={"name": "acme"})

        assert response.status_code == 401
        assert response.headers["WWW-Authenticate"] == "Bearer"
        assert response.json() == {"detail": "invalid or expired token"}

        unknown = client.post(
            "/iam/tenants",
            json={"name": "acme"},
            headers={"Authorization": "Bearer iam_sess_00000000-0000-0000-0000-000000000001"},
        )
        assert unknown.status_code == 401
        assert unknown.json() == {"detail": "invalid or expired token"}


def test_mention_search_is_open_to_any_signed_in_user(config_dir: Any) -> None:
    """The ``@`` autocomplete works for a plain user, while the user list stays admin-only."""
    seed_admin("root@example.com")

    with TestClient(create_app()) as client:
        wait_for(lambda: client.get("/iam/bootstrap").json()["completed"])
        admin = login(client, "root@example.com")
        created = client.post(
            "/iam/users",
            json={"username": "alice", "email": "alice@example.com"},
            headers=admin,
        )
        assert created.status_code == 201, created.text
        user_id = created.json()["user_id"]
        client.post(
            f"/iam/users/{user_id}/identities/password",
            json={"password": PASSWORD},
            headers=admin,
        )
        member = login(client, "alice")

        assert client.get("/iam/users", headers=member).status_code == 403

        hits = wait_for(
            lambda: client.get(
                "/iam/users/search", params={"term": "ali"}, headers=member
            ).json()
            or None
        )
        assert [hit["username"] for hit in hits] == ["alice"]
        assert set(hits[0]) == {"user_id", "username", "display_name"}

        exact = client.get(
            "/iam/users/search", params={"term": "alice@example.com"}, headers=member
        ).json()
        assert [hit["user_id"] for hit in exact] == [user_id]
        assert exact[0]["display_name"] == "alice"

        assert (
            client.get("/iam/users/search", params={"term": "zzz"}, headers=member).json() == []
        )

        # A bare `@` sends no term at all: the endpoint then answers the first users.
        everyone = client.get("/iam/users/search", headers=member)
        assert everyone.status_code == 200, everyone.text
        assert {hit["username"] for hit in everyone.json()} == {"alice", "root@example.com"}
        assert len(client.get("/iam/users/search", params={"term": ""}, headers=member).json()) == 2

        assert client.get("/iam/users/search", params={"term": "a"}).status_code == 401
