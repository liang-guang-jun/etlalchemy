"""Tests for the agent HTTP routes."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from typing import Any

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


def login(client: TestClient, email: str) -> dict[str, str]:
    """Authenticates and returns the bearer headers."""
    body = {"login": email, "password": PASSWORD}
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


def test_provider_and_conversation_lifecycle(config_dir: Any) -> None:
    """A provider and a conversation are created, read, changed and discarded."""
    seed_admin("root@example.com")

    with TestClient(create_app()) as client:
        headers = login(client, "root@example.com")

        created = client.post(
            "/agent/llm-providers",
            headers=headers,
            json={
                "name": "my-openai",
                "kind": "openai",
                "credential_ref": "env:OPENAI_API_KEY",
                "default_model": "gpt-4o-mini",
            },
        )
        assert created.status_code == 201, created.text
        provider_id = created.json()["provider_id"]

        listed = wait_for(
            lambda: client.get("/agent/llm-providers", headers=headers).json(),
        )
        assert [row["provider_id"] for row in listed] == [provider_id]

        fetched = client.get(f"/agent/llm-providers/{provider_id}", headers=headers)
        assert fetched.status_code == 200
        assert fetched.json()["credential_ref"] == "env:OPENAI_API_KEY"
        assert "token" not in fetched.json()

        renamed = client.patch(
            f"/agent/llm-providers/{provider_id}",
            headers=headers,
            json={"name": "renamed"},
        )
        assert renamed.status_code == 200

        conversation = client.post(
            "/agent/conversations",
            headers=headers,
            json={"title": "pricing"},
        )
        assert conversation.status_code == 201, conversation.text
        conversation_id = conversation.json()["conversation_id"]

        listed_conversations = wait_for(
            lambda: client.get("/agent/conversations", headers=headers).json(),
        )
        assert [row["conversation_id"] for row in listed_conversations] == [conversation_id]

        messages = client.get(
            f"/agent/conversations/{conversation_id}/messages",
            headers=headers,
        )
        assert messages.status_code == 200
        assert messages.json() == []

        assert (
            client.delete(
                f"/agent/conversations/{conversation_id}",
                headers=headers,
            ).status_code
            == 204
        )
        assert (
            client.delete(
                f"/agent/llm-providers/{provider_id}",
                headers=headers,
            ).status_code
            == 204
        )


def test_agent_routes_require_a_token(config_dir: Any) -> None:
    """Every agent route rejects an anonymous caller."""
    seed_admin("root@example.com")

    with TestClient(create_app()) as client:
        assert client.get("/agent/llm-providers").status_code == 401
        assert client.get("/agent/conversations").status_code == 401
