"""Tests for the catalog HTTP routes."""

import time
from collections.abc import Callable
from pathlib import Path
from typing import Any
from uuid import uuid4

from eventsourcing.persistence import IntegrityError
from fastapi import FastAPI
from fastapi.testclient import TestClient

from etlalchemy.app.api.app import create_app
from etlalchemy.app.api.routes.catalog import add_exception_handlers

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


def test_catalog_api_roundtrip(config_dir: Path) -> None:
    """Writes through the application and reads from the read model."""
    app = create_app()
    with TestClient(app) as client:
        created = client.post("/api/catalog/catalogs", params={"name": "analytics"})
        assert created.status_code == 200
        catalog_id = created.json()["catalog_id"]

        schema = client.post(
            f"/api/catalog/catalogs/{catalog_id}/schemas",
            params={"schema_name": "sales", "description": "Sales data"},
        )
        assert schema.status_code == 200
        assert "schema_id" in schema.json()

        table = client.post(
            f"/api/catalog/catalogs/{catalog_id}/schemas/sales/tables",
            params={"table_name": "orders"},
        )
        assert table.status_code == 200

        field = client.post(
            f"/api/catalog/catalogs/{catalog_id}/schemas/sales/tables/orders/fields",
            params={"field_name": "id", "data_type": "integer", "nullable": False},
        )
        assert field.status_code == 200

        patched = client.patch(
            f"/api/catalog/catalogs/{catalog_id}/schemas/sales/tables/orders",
            json={"description": "Orders fact table"},
        )
        assert patched.status_code == 200

        def table_payload() -> dict[str, Any]:
            response = client.get(
                f"/api/catalog/catalogs/{catalog_id}/schemas/sales/tables/orders"
            )
            if response.status_code != 200:
                return {}
            payload: dict[str, Any] = response.json()
            return payload if payload.get("description") == "Orders fact table" else {}

        table = wait_for(table_payload)
        assert table["name"] == "orders"
        assert client.patch(
            f"/api/catalog/catalogs/{catalog_id}/schemas/sales/tables/orders", json={}
        ).status_code == 400

        catalogs = wait_for(lambda: client.get("/api/catalog/catalogs").json())
        assert [(row["catalog_id"], row["name"]) for row in catalogs] == [
            (catalog_id, "analytics")
        ]

        fetched = client.get(f"/api/catalog/catalogs/{catalog_id}")
        assert fetched.status_code == 200
        assert fetched.json()["name"] == "analytics"

        assert client.get(f"/api/catalog/catalogs/{uuid4()}").status_code == 404

        schemas = wait_for(
            lambda: client.get(f"/api/catalog/catalogs/{catalog_id}/schemas").json()
        )
        assert [(row["name"], row["description"]) for row in schemas] == [
            ("sales", "Sales data")
        ]

        results = wait_for(lambda: client.get("/api/catalog/search", params={"term": "id"}).json())
        assert [(row["schema_name"], row["table_name"], row["field_name"]) for row in results] == [
            ("sales", "orders", "id")
        ]
        assert results[0]["nullable"] is False

        objects = wait_for(
            lambda: client.get("/api/catalog/search-objects", params={"term": "ord"}).json()
        )
        assert [(row["kind"], row["name"], row["path"]) for row in objects] == [
            ("table", "orders", "analytics / sales / orders")
        ]
        assert client.get("/api/catalog/search-objects", params={"term": "  "}).json() == []

        fields_by_table = wait_for(
            lambda: client.get(f"/api/catalog/tables/{table['table_id']}/fields").json()
        )
        assert [(row["name"], row["data_type"]) for row in fields_by_table] == [("id", "integer")]
        assert client.get(f"/api/catalog/tables/{uuid4()}/fields").status_code == 404

        location = client.get(f"/api/catalog/tables/{table['table_id']}").json()
        assert location == {
            "table_id": table["table_id"],
            "name": "orders",
            "catalog_id": catalog_id,
            "schema_id": table["schema_id"],
            "schema_name": "sales",
        }
        assert client.get(f"/api/catalog/tables/{uuid4()}").status_code == 404


def test_catalog_api_maps_domain_errors(config_dir: Path) -> None:
    """Domain errors become 409 conflict or 404 not-found responses."""
    app = create_app()
    with TestClient(app) as client:
        catalog_id = client.post(
            "/api/catalog/catalogs", params={"name": "analytics"}
        ).json()["catalog_id"]

        first = client.post(
            f"/api/catalog/catalogs/{catalog_id}/schemas",
            params={"schema_name": "sales"},
        )
        assert first.status_code == 200

        duplicate = client.post(
            f"/api/catalog/catalogs/{catalog_id}/schemas",
            params={"schema_name": "sales"},
        )
        assert duplicate.status_code == 409
        assert "sales" in duplicate.json()["detail"]

        missing = client.post(
            f"/api/catalog/catalogs/{catalog_id}/schemas/warehouse/tables",
            params={"table_name": "orders"},
        )
        assert missing.status_code == 404
        assert "warehouse" in missing.json()["detail"]


def test_catalog_api_maps_record_conflicts() -> None:
    """Optimistic concurrency failures answer 409 instead of 500."""
    app = FastAPI()
    add_exception_handlers(app)

    @app.get("/conflict")
    def conflict() -> None:
        raise IntegrityError("duplicate key value violates unique constraint")

    with TestClient(app) as client:
        response = client.get("/conflict")

    assert response.status_code == 409
    assert "duplicate key" in response.json()["detail"]

