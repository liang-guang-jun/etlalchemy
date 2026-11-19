"""Tests for the shared bearer authentication of the HTTP API."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from typing import Any

from etlalchemy.app.api.app import create_app
from etlalchemy.app.bootstrap.factories import get_iam_env
from etlalchemy.app.bootstrap.settings import load_app_settings
from etlalchemy.iam.adapters.passwords import PasswordHasher
from etlalchemy.iam.aggregates.identity import Identity
from etlalchemy.iam.aggregates.user import User
from etlalchemy.iam.projection.projection import IamEventApplication
from fastapi.testclient import TestClient

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


def form_login(client: TestClient, email: str, scope: str = "") -> Any:
    """Submits the OAuth2 password grant form."""
    return client.post(
        "/iam/auth/token",
        data={"username": email, "password": PASSWORD, "scope": scope},
    )


def wait_for_form_login(client: TestClient, email: str, scope: str = "") -> Any:
    """Retries the password grant until the projection knows the credential."""
    deadline = time.monotonic() + WAIT_TIMEOUT
    response = form_login(client, email, scope)
    while response.status_code != 200 and time.monotonic() < deadline:
        time.sleep(0.05)
        response = form_login(client, email, scope)
    assert response.status_code == 200, response.text
    return response


def test_form_login_returns_a_usable_bearer_token(config_dir: Any) -> None:
    """The password grant answers an access token the protected routes accept."""
    seed_admin("root@example.com")

    with TestClient(create_app()) as client:
        wait_for(lambda: client.get("/iam/bootstrap").json()["completed"])

        response = wait_for_form_login(client, "root@example.com")

        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["token_type"] == "bearer"
        assert payload["access_token"].startswith("iam_sess_")

        headers = {"Authorization": f"Bearer {payload['access_token']}"}
        current = wait_for(
            lambda: client.get("/iam/sessions/current", headers=headers).json()
            if client.get("/iam/sessions/current", headers=headers).status_code == 200
            else None,
        )
        assert current["session_id"] == payload["session_id"]
        assert current["access_token"] == payload["access_token"]


def test_form_login_rejects_a_malformed_tenant_scope(config_dir: Any) -> None:
    """A ``tenant:`` entry that is not a UUID is a caller error."""
    seed_admin("root@example.com")

    with TestClient(create_app()) as client:
        wait_for(lambda: client.get("/iam/bootstrap").json()["completed"])

        response = form_login(client, "root@example.com", "tenant:not-a-uuid")

        assert response.status_code == 400
        assert response.json() == {"detail": "invalid tenant scope"}


def test_form_login_carries_the_tenant_in_the_scope(config_dir: Any) -> None:
    """``scope=tenant:<uuid>`` selects the tenant of the issued session."""
    seed_admin("root@example.com")

    with TestClient(create_app()) as client:
        wait_for(lambda: client.get("/iam/bootstrap").json()["completed"])
        root = wait_for_form_login(client, "root@example.com").json()
        headers = {"Authorization": f"Bearer {root['access_token']}"}
        wait_for(lambda: client.get("/iam/sessions/current", headers=headers).status_code == 200)
        tenant_id = client.post(
            "/iam/tenants",
            json={"name": "acme"},
            headers=headers,
        ).json()["tenant_id"]
        user_id = client.post(
            "/iam/users",
            json={"username": "alice", "email": "alice@example.com"},
            headers=headers,
        ).json()["user_id"]
        client.post(
            f"/iam/users/{user_id}/identities/password",
            json={"password": PASSWORD},
            headers=headers,
        )
        client.post(
            f"/iam/tenants/{tenant_id}/members",
            json={"user_id": user_id},
            headers=headers,
        )
        wait_for(
            lambda: client.get(
                f"/iam/tenants/{tenant_id}/members",
                headers=headers,
            ).status_code
            == 200
            and "alice"
            in [
                member["username"]
                for member in client.get(
                    f"/iam/tenants/{tenant_id}/members",
                    headers=headers,
                ).json()
            ],
        )

        response = wait_for_form_login(client, "alice", f"tenant:{tenant_id}")

        assert response.status_code == 200, response.text
        assert response.json()["tenant_id"] == tenant_id


def test_logout_invalidates_the_token(config_dir: Any) -> None:
    """The token stops working as soon as the session behind it is revoked."""
    seed_admin("root@example.com")

    with TestClient(create_app()) as client:
        wait_for(lambda: client.get("/iam/bootstrap").json()["completed"])
        payload = wait_for_form_login(client, "root@example.com").json()
        headers = {"Authorization": f"Bearer {payload['access_token']}"}
        wait_for(lambda: client.get("/iam/sessions/current", headers=headers).status_code == 200)

        assert client.post("/iam/auth/logout", headers=headers).status_code == 204

        rejected = wait_for(
            lambda: client.get("/iam/sessions/current", headers=headers)
            if client.get("/iam/sessions/current", headers=headers).status_code == 401
            else None,
        )
        assert rejected.json() == {"detail": "invalid or expired token"}


def test_openapi_advertises_the_password_flow(config_dir: Any) -> None:
    """Swagger UI finds the token endpoint of the OAuth2 password flow."""
    with TestClient(create_app()) as client:
        schema = client.get("/openapi.json").json()

    scheme = schema["components"]["securitySchemes"]["OAuth2PasswordBearer"]
    assert scheme["flows"]["password"]["tokenUrl"] == "/iam/auth/token"
