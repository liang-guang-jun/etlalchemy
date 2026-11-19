"""Tests for the comment HTTP routes."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from typing import Any
from uuid import uuid4

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


def login(client: TestClient, email: str) -> dict[str, str]:
    """Authenticates and waits for the session row, returning the bearer headers."""
    body = {"login": email, "password": PASSWORD}
    deadline = time.monotonic() + WAIT_TIMEOUT
    response = client.post("/iam/auth/password", json=body)
    while response.status_code != 200 and time.monotonic() < deadline:
        time.sleep(0.05)
        response = client.post("/iam/auth/password", json=body)
    assert response.status_code == 200, response.text
    headers = {"Authorization": f"Bearer {response.json()['access_token']}"}
    wait_for(lambda: client.get("/iam/sessions/current", headers=headers).status_code == 200)
    return headers


def test_thread_lifecycle(config_dir: Any) -> None:
    """A thread is created, replied to, edited, resolved, reopened and discarded."""
    seed_admin("root@example.com")

    with TestClient(create_app()) as client:
        wait_for(lambda: client.get("/iam/bootstrap").json()["completed"])
        headers = login(client, "root@example.com")
        target = str(uuid4())

        created = client.post(
            "/comments/threads",
            json={
                "target_type": "table",
                "target_id": target,
                "body": "root body",
                "title": "pricing",
            },
            headers=headers,
        )
        assert created.status_code == 201, created.text
        thread_id = created.json()["thread_id"]
        root_id = created.json()["root_comment_id"]

        listed = wait_for(
            lambda: client.get(
                "/comments/threads",
                params={"target_type": "table", "target_id": target},
                headers=headers,
            ).json()
            or None
        )
        assert [row["thread_id"] for row in listed] == [thread_id]
        assert listed[0]["comment_count"] == 1

        reply = client.post(
            f"/comments/threads/{thread_id}/comments",
            json={"body": "first reply", "parent_comment_id": root_id},
            headers=headers,
        )
        assert reply.status_code == 201, reply.text
        assert reply.json()["depth"] == 1
        assert reply.json()["depth_warning"] is None
        reply_id = reply.json()["comment_id"]

        detail = wait_for(
            lambda: (
                lambda response: response.json()
                if response.status_code == 200 and response.json()["thread"]["comment_count"] == 2
                else None
            )(client.get(f"/comments/threads/{thread_id}", headers=headers))
        )
        assert [row["depth"] for row in detail["comments"]] == [0, 1]

        edited = client.patch(
            f"/comments/threads/{thread_id}/comments/{reply_id}",
            json={"body": "edited reply"},
            headers=headers,
        )
        assert edited.status_code == 200, edited.text
        wait_for(
            lambda: client.get(
                f"/comments/threads/{thread_id}",
                headers=headers,
            ).json()["comments"][1]["body"]
            == "edited reply"
        )

        flattened = wait_for(
            lambda: (
                lambda response: response.json()
                if response.status_code == 200 and len(response.json()) == 2
                else None
            )(
                client.get(
                    f"/comments/threads/{thread_id}/comments",
                    params={"flatten_after": 0},
                    headers=headers,
                )
            )
        )
        assert [row["depth"] for row in flattened] == [0, 0]

        resolved = client.post(
            f"/comments/threads/{thread_id}/resolve",
            headers=headers,
        )
        assert resolved.status_code == 200, resolved.text

        reopened = client.post(
            f"/comments/threads/{thread_id}/reopen",
            headers=headers,
        )
        assert reopened.status_code == 200, reopened.text

        discarded = client.delete(
            f"/comments/threads/{thread_id}/comments/{reply_id}",
            headers=headers,
        )
        assert discarded.status_code == 204, discarded.text

        discarded_thread = client.delete(
            f"/comments/threads/{thread_id}",
            headers=headers,
        )
        assert discarded_thread.status_code == 204, discarded_thread.text
        wait_for(
            lambda: client.get(
                f"/comments/threads/{thread_id}",
                headers=headers,
            ).status_code
            == 404
        )


def test_error_status_mapping(config_dir: Any) -> None:
    """Domain errors map to 400, 401, 404 and 409."""
    seed_admin("root@example.com")

    with TestClient(create_app()) as client:
        wait_for(lambda: client.get("/iam/bootstrap").json()["completed"])
        headers = login(client, "root@example.com")
        target = str(uuid4())

        missing_session = client.get("/comments/threads")
        assert missing_session.status_code == 401

        # Diagrams are still keyed by name inside their model, so the type is not
        # registered and the thread is rejected before any lookup.
        unregistered = client.post(
            "/comments/threads",
            json={
                "target_type": "diagram",
                "target_id": target,
                "body": "body",
            },
            headers=headers,
        )
        assert unregistered.status_code == 404

        blank = client.post(
            "/comments/threads",
            json={"target_type": "table", "target_id": target, "body": "   "},
            headers=headers,
        )
        assert blank.status_code == 400

        created = client.post(
            "/comments/threads",
            json={"target_type": "table", "target_id": target, "body": "root"},
            headers=headers,
        )
        thread_id = created.json()["thread_id"]

        unknown_thread = client.get(
            f"/comments/threads/{uuid4()}",
            headers=headers,
        )
        assert unknown_thread.status_code == 404

        unknown_parent = client.post(
            f"/comments/threads/{thread_id}/comments",
            json={"body": "reply", "parent_comment_id": str(uuid4())},
            headers=headers,
        )
        assert unknown_parent.status_code == 404

        assert (
            client.post(
                f"/comments/threads/{thread_id}/resolve",
                headers=headers,
            ).status_code
            == 200
        )
        assert (
            client.post(
                f"/comments/threads/{thread_id}/resolve",
                headers=headers,
            ).status_code
            == 409
        )


def _catalog_field(client: TestClient, headers: dict[str, str]) -> dict[str, Any]:
    """Creates a catalog, schema, table and field and returns the field row."""
    catalog_id = client.post(
        "/catalog/catalogs", params={"name": "Customer 360"}, headers=headers
    ).json()["catalog_id"]
    client.post(
        f"/catalog/catalogs/{catalog_id}/schemas",
        params={"schema_name": "crm"},
        headers=headers,
    )
    table_id = client.post(
        f"/catalog/catalogs/{catalog_id}/schemas/crm/tables",
        params={"table_name": "contacts"},
        headers=headers,
    ).json()["table_id"]
    client.post(
        f"/catalog/catalogs/{catalog_id}/schemas/crm/tables/contacts/fields",
        params={"field_name": "contact_id", "data_type": "uuid"},
        headers=headers,
    )
    url = f"/catalog/catalogs/{catalog_id}/schemas/crm/tables/contacts/fields"
    fields = wait_for(
        lambda: (
            lambda response: response.json()
            if response.status_code == 200 and response.json()
            else None
        )(client.get(url, headers=headers))
    )
    return {"catalog_id": catalog_id, "table_id": table_id, "field": fields[0]}


def test_field_and_entity_carry_an_identity(config_dir: Any) -> None:
    """Fields and semantic entities expose a UUID that survives a rename."""
    seed_admin("root@example.com")

    with TestClient(create_app()) as client:
        wait_for(lambda: client.get("/iam/bootstrap").json()["completed"])
        headers = login(client, "root@example.com")
        created = _catalog_field(client, headers)
        field_id = created["field"]["field_id"]

        renamed = client.post(
            f"/catalog/catalogs/{created['catalog_id']}/schemas/crm/tables/contacts/fields/"
            "contact_id/rename",
            json={"new_name": "contact_key"},
            headers=headers,
        )
        assert renamed.status_code == 200, renamed.text
        renamed_field = wait_for(
            lambda: (
                lambda rows: rows[0] if rows and rows[0]["name"] == "contact_key" else None
            )(
                (
                    lambda response: response.json() if response.status_code == 200 else []
                )(
                    client.get(
                        "/catalog/catalogs/"
                        f"{created['catalog_id']}/schemas/crm/tables/contacts/fields",
                        headers=headers,
                    )
                )
            )
        )
        assert renamed_field["field_id"] == field_id

        model_id = client.post(
            "/semantic/models", json={"name": "Compensation 360"}, headers=headers
        ).json()["model_id"]
        entity = client.post(
            f"/semantic/models/{model_id}/entities",
            json={"name": "Employee", "table_id": created["table_id"]},
            headers=headers,
        ).json()
        assert entity["entity_id"] is not None
        entity_id = entity["entity_id"]

        listed = wait_for(
            lambda: (
                lambda response: response.json() if response.status_code == 200 else None
            )(client.get(f"/semantic/models/{model_id}/entities", headers=headers))
            and client.get(f"/semantic/models/{model_id}/entities", headers=headers).json()
        )
        assert listed[0]["entity_id"] == entity_id


def test_target_descriptions_name_the_object(config_dir: Any) -> None:
    """A field and an entity can be discussed and are described with their path."""
    seed_admin("root@example.com")

    with TestClient(create_app()) as client:
        wait_for(lambda: client.get("/iam/bootstrap").json()["completed"])
        headers = login(client, "root@example.com")
        created = _catalog_field(client, headers)
        field_id = created["field"]["field_id"]

        model_id = client.post(
            "/semantic/models", json={"name": "Compensation 360"}, headers=headers
        ).json()["model_id"]
        entity_id = client.post(
            f"/semantic/models/{model_id}/entities",
            json={"name": "Employee", "table_id": created["table_id"]},
            headers=headers,
        ).json()["entity_id"]

        for target_type, target_id in (("field", field_id), ("semantic_entity", entity_id)):
            thread = client.post(
                "/comments/threads",
                json={
                    "target_type": target_type,
                    "target_id": target_id,
                    "body": "look here",
                },
                headers=headers,
            )
            assert thread.status_code == 201, thread.text

        field_target = client.get(
            f"/comments/targets/field/{field_id}", headers=headers
        )
        assert field_target.status_code == 200, field_target.text
        described = field_target.json()
        assert described["name"] == "contact_id"
        assert described["path"] == "Customer 360 / crm / contacts / contact_id"
        assert described["catalog_id"] == created["catalog_id"]
        assert described["schema_name"] == "crm"
        assert described["table_name"] == "contacts"

        entity_target = wait_for(
            lambda: (
                lambda response: response.json()
                if response.status_code == 200
                else None
            )(
                client.get(
                    f"/comments/targets/semantic_entity/{entity_id}", headers=headers
                )
            )
        )
        assert entity_target["path"] == "Compensation 360 / Employee"
        assert entity_target["model_id"] == model_id
        assert entity_target["entity_name"] == "Employee"

        batch = client.post(
            "/comments/targets/lookup",
            json={
                "refs": [
                    {"target_type": "field", "target_id": field_id},
                    {"target_type": "semantic_entity", "target_id": entity_id},
                    {"target_type": "field", "target_id": field_id},
                    {"target_type": "table", "target_id": str(uuid4())},
                ]
            },
            headers=headers,
        )
        assert batch.status_code == 200, batch.text
        assert [row["target_type"] for row in batch.json()] == ["field", "semantic_entity"]

        unknown = client.get(
            f"/comments/targets/semantic_entity/{uuid4()}", headers=headers
        )
        assert unknown.status_code == 404
