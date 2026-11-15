"""Tests for the semantic HTTP routes."""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from etlalchemy.app.api.app import create_app

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


def create_catalog(client: TestClient) -> dict[str, str]:
    """Creates a catalog with the customers and orders tables."""
    catalog = client.post("/api/catalog/catalogs", params={"name": "analytics"})
    assert catalog.status_code == 200
    catalog_id = catalog.json()["catalog_id"]
    assert (
        client.post(
            f"/api/catalog/catalogs/{catalog_id}/schemas",
            params={"schema_name": "sales"},
        ).status_code
        == 200
    )
    tables: dict[str, str] = {}
    for table_name, fields in (
        ("customers", ("id", "name")),
        ("orders", ("id", "customer_id")),
    ):
        table = client.post(
            f"/api/catalog/catalogs/{catalog_id}/schemas/sales/tables",
            params={"table_name": table_name},
        )
        assert table.status_code == 200
        tables[table_name] = table.json()["table_id"]
        fields_url = f"/api/catalog/catalogs/{catalog_id}/schemas/sales/tables/{table_name}/fields"
        for field_name in fields:
            assert (
                client.post(
                    fields_url,
                    params={
                        "field_name": field_name,
                        "data_type": "integer",
                        "nullable": False,
                    },
                ).status_code
                == 200
            )

        def fields_ready(url: str = fields_url) -> bool:
            response = client.get(url)
            return response.status_code == 200 and bool(response.json())

        wait_for(fields_ready)
    return tables


def create_model(client: TestClient) -> tuple[str, dict[str, str]]:
    """Creates a model with the customers and orders entities."""
    tables = create_catalog(client)
    model = client.post("/api/semantic/models", json={"name": "sales", "description": "Revenue"})
    assert model.status_code == 201
    model_id = model.json()["model_id"]
    base = f"/api/semantic/models/{model_id}"
    for name in ("customers", "orders"):
        created = client.post(
            f"{base}/entities",
            json={"name": name, "table_id": tables[name]},
        )
        assert created.status_code == 201
        assert created.json()["name"] == name

    def entities_ready() -> bool:
        rows = client.get(f"{base}/entities")
        return rows.status_code == 200 and len(rows.json()) == 2

    wait_for(entities_ready)
    return model_id, tables


def add_relationship(client: TestClient, model_id: str) -> str:
    """Adds the customers.id -> orders.customer_id relationship."""
    response = client.post(
        f"/api/semantic/models/{model_id}/relationships",
        json={
            "from_refs": [{"entity": "customers", "field": "id"}],
            "to_refs": [{"entity": "orders", "field": "customer_id"}],
            "cardinality": "one_to_many",
            "filter_direction": "both",
            "priority": 2,
        },
    )
    assert response.status_code == 201
    relationship_id: str = response.json()["relationship_id"]
    return relationship_id


def test_model_roundtrip(config_dir: Path) -> None:
    """A model, its entities, relationship, diagram and nodes round-trip."""
    app = create_app()
    with TestClient(app) as client:
        model_id, tables = create_model(client)
        base = f"/api/semantic/models/{model_id}"
        relationship_id = add_relationship(client, model_id)
        assert client.post(f"{base}/diagrams", json={"name": "detail", "order": 1}).status_code == 201
        node = client.post(f"{base}/diagrams/detail/nodes", json={"entity_name": "orders"})
        assert node.status_code == 201
        assert node.json()["diagram_name"] == "detail"

        assert client.get(f"{base}").json()["name"] == "sales"
        assert [row["name"] for row in client.get("/api/semantic/models").json()] == ["sales"]
        entity = client.get(f"{base}/entities/customers")
        assert entity.status_code == 200
        assert entity.json()["table_id"] == tables["customers"]

        def relationship_ready() -> bool:
            return client.get(f"{base}/relationships/{relationship_id}").status_code == 200

        wait_for(relationship_ready)
        relationship = client.get(f"{base}/relationships/{relationship_id}")
        assert relationship.status_code == 200
        assert relationship.json()["from_refs"] == [{"entity": "customers", "field": "id"}]
        assert relationship.json()["cardinality"] == "one_to_many"

        def nodes_ready() -> bool:
            rows = client.get(f"{base}/diagrams/detail/nodes").json()
            return [row["entity_name"] for row in rows] == ["orders"]

        wait_for(nodes_ready)
        moved = client.patch(
            f"{base}/diagrams/detail/nodes/orders",
            json={"x": 12.5, "y": 20.0},
        )
        assert moved.status_code == 200

        def node_moved() -> bool:
            rows = client.get(f"{base}/diagrams/detail/nodes").json()
            return bool(rows) and rows[0]["x"] == 12.5 and rows[0]["y"] == 20.0

        wait_for(node_moved)
        all_nodes = client.get(f"{base}/diagrams/All/nodes").json()
        assert sorted(row["entity_name"] for row in all_nodes) == ["customers", "orders"]

        renamed = client.patch(f"{base}/entities/customers", json={"new_name": "clients"})
        assert renamed.status_code == 200

        def rename_visible() -> bool:
            rows = client.get(f"{base}/entities").json()
            return [row["name"] for row in rows] == ["clients", "orders"]

        wait_for(rename_visible)
        assert client.get(f"{base}/entities/customers").status_code == 404
        assert client.delete(f"{base}/relationships/{relationship_id}").status_code == 204
        assert client.delete(f"{base}/entities/clients").status_code == 204
        assert client.delete(f"{base}/diagrams/detail").status_code == 204
        assert client.delete(f"{base}").status_code == 204


def test_the_all_diagram_rejects_manual_nodes(config_dir: Path) -> None:
    """The overview manages its own nodes but still accepts moves."""
    app = create_app()
    with TestClient(app) as client:
        model_id, _ = create_model(client)
        base = f"/api/semantic/models/{model_id}"

        created = client.post(f"{base}/diagrams/All/nodes", json={"entity_name": "orders"})
        removed = client.delete(f"{base}/diagrams/All/nodes/orders")
        moved = client.patch(
            f"{base}/diagrams/All/nodes/orders",
            json={"x": 100.0, "y": 200.0},
        )

        assert created.status_code == 409
        assert removed.status_code == 409
        assert moved.status_code == 200


def test_unknown_references_answer_404(config_dir: Path) -> None:
    """Unknown models, entities, diagrams and relationships answer 404."""
    app = create_app()
    with TestClient(app) as client:
        model_id, _ = create_model(client)
        base = f"/api/semantic/models/{model_id}"
        missing = "00000000-0000-0000-0000-000000000000"

        assert client.get(f"/api/semantic/models/{missing}").status_code == 404
        assert client.get(f"{base}/entities/ghosts").status_code == 404
        assert client.get(f"{base}/diagrams/missing").status_code == 404
        assert client.get(f"{base}/relationships/{missing}").status_code == 404


def test_a_discarded_model_hides_its_children(config_dir: Path) -> None:
    """Nested reads of a discarded model answer 404 instead of an empty list."""
    app = create_app()
    with TestClient(app) as client:
        model_id, _ = create_model(client)
        base = f"/api/semantic/models/{model_id}"

        assert client.delete(base).status_code == 204

        def discarded() -> bool:
            return client.get(base).status_code == 404

        wait_for(discarded)
        assert client.get(f"{base}/entities").status_code == 404
        assert client.get(f"{base}/diagrams").status_code == 404
        assert client.get(f"{base}/relationships").status_code == 404
        assert client.post(f"{base}/diagrams", json={"name": "detail"}).status_code == 409


def test_invalid_writes_are_mapped_to_their_status(config_dir: Path) -> None:
    """Conflicts answer 409, caller errors 400 and unknown tables 404."""
    app = create_app()
    with TestClient(app) as client:
        model_id, tables = create_model(client)
        base = f"/api/semantic/models/{model_id}"

        bad_field = client.post(
            f"{base}/relationships",
            json={
                "from_refs": [{"entity": "customers", "field": "id"}],
                "to_refs": [{"entity": "orders", "field": "ghost"}],
                "cardinality": "one_to_many",
            },
        )
        empty_patch = client.patch(f"{base}/entities/customers", json={})
        duplicate = client.post(
            f"{base}/entities",
            json={"name": "customers", "table_id": tables["customers"]},
        )
        unknown_table = client.post(
            f"{base}/entities",
            json={
                "name": "lines",
                "table_id": "00000000-0000-0000-0000-000000000000",
            },
        )

        assert bad_field.status_code == 409
        assert empty_patch.status_code == 400
        assert duplicate.status_code == 409
        assert unknown_table.status_code == 404


def test_patch_entity_renames_before_changing_the_table(config_dir: Path) -> None:
    """A rename and a table change in one body apply to the same entity."""
    app = create_app()
    with TestClient(app) as client:
        model_id, tables = create_model(client)
        base = f"/api/semantic/models/{model_id}"

        response = client.patch(
            f"{base}/entities/customers",
            json={"new_name": "clients", "table_id": tables["orders"]},
        )

        assert response.status_code == 200

        def renamed() -> bool:
            row = client.get(f"{base}/entities/clients")
            return row.status_code == 200 and row.json()["table_id"] == tables["orders"]

        wait_for(renamed)
