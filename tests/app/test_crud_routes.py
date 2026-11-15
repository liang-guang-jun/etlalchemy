"""Tests for the catalog CRUD HTTP routes."""

import time
from collections.abc import Callable
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi.testclient import TestClient

from etlalchemy.app.api.app import create_app

WAIT_TIMEOUT = 10.0


def wait_for(predicate: Callable[[], Any], timeout: float = WAIT_TIMEOUT) -> None:
    """Polls ``predicate`` until it returns a truthy value."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.05)
    raise AssertionError("timed out waiting for the projection")


def create_tree(client: TestClient) -> str:
    """Creates a catalog, schema, table and field and waits for the read model."""
    catalog_id = client.post("/api/catalog/catalogs", params={"name": "analytics"}).json()[
        "catalog_id"
    ]
    client.post(
        f"/api/catalog/catalogs/{catalog_id}/schemas",
        params={"schema_name": "sales", "description": "Sales data"},
    )
    client.post(
        f"/api/catalog/catalogs/{catalog_id}/schemas/sales/tables",
        params={"table_name": "orders"},
    )
    client.post(
        f"/api/catalog/catalogs/{catalog_id}/schemas/sales/tables/orders/fields",
        params={"field_name": "id", "data_type": "integer", "nullable": False},
    )
    wait_for(lambda: searches(client, "id"))
    return catalog_id


def searches(client: TestClient, term: str) -> list[dict[str, Any]]:
    """Returns the search results for a term."""
    return client.get("/api/catalog/search", params={"term": term}).json()


def first_search(client: TestClient, term: str) -> dict[str, Any]:
    """Returns the first search result for a term, or an empty mapping."""
    results = searches(client, term)
    return results[0] if results else {}


def schema_names(client: TestClient, catalog_id: str) -> list[str]:
    """Returns the schema names the read model lists for a catalog."""
    return [
        row["name"]
        for row in client.get(f"/api/catalog/catalogs/{catalog_id}/schemas").json()
    ]


def test_patch_and_delete_routes_update_the_read_model(config_dir: Path) -> None:
    """Renames and field edits flow through the application into the read model."""
    with TestClient(create_app()) as client:
        catalog_id = create_tree(client)

        renamed = client.patch(
            f"/api/catalog/catalogs/{catalog_id}",
            json={"name": "warehouse", "description": "Warehouse catalog"},
        )
        assert renamed.status_code == 200
        wait_for(
            lambda: client.get(f"/api/catalog/catalogs/{catalog_id}").json().get("name")
            == "warehouse"
        )
        catalog = client.get(f"/api/catalog/catalogs/{catalog_id}").json()
        assert catalog["description"] == "Warehouse catalog"

        schema = client.patch(
            f"/api/catalog/catalogs/{catalog_id}/schemas/sales",
            json={"name": "revenue", "description": "Revenue data"},
        )
        assert schema.status_code == 200
        wait_for(lambda: schema_names(client, catalog_id) == ["revenue"])
        schemas = client.get(f"/api/catalog/catalogs/{catalog_id}/schemas").json()
        assert schemas[0]["description"] == "Revenue data"

        table = client.patch(
            f"/api/catalog/catalogs/{catalog_id}/schemas/revenue/tables/orders",
            json={"name": "purchases"},
        )
        assert table.status_code == 200
        wait_for(
            lambda: first_search(client, "id").get("table_name") == "purchases"
        )

        field = client.patch(
            f"/api/catalog/catalogs/{catalog_id}/schemas/revenue/tables/purchases/fields/id",
            json={"data_type": "bigint"},
        )
        assert field.status_code == 200
        wait_for(lambda: first_search(client, "id").get("data_type") == "bigint")

        renamed_field = client.post(
            f"/api/catalog/catalogs/{catalog_id}/schemas/revenue/tables/purchases"
            "/fields/id/rename",
            json={"new_name": "order_id"},
        )
        assert renamed_field.status_code == 200
        wait_for(
            lambda: first_search(client, "order_id").get("field_name") == "order_id"
        )
        assert first_search(client, "order_id")["data_type"] == "bigint"

        removed = client.delete(
            f"/api/catalog/catalogs/{catalog_id}/schemas/revenue/tables/purchases/fields/order_id"
        )
        assert removed.status_code == 204
        assert removed.content == b""
        wait_for(lambda: searches(client, "order_id") == [])


def test_delete_discards_a_catalog_and_hides_it(config_dir: Path) -> None:
    """A discarded catalog disappears from the read model."""
    with TestClient(create_app()) as client:
        catalog_id = create_tree(client)

        discarded = client.delete(f"/api/catalog/catalogs/{catalog_id}")
        assert discarded.status_code == 204
        assert discarded.content == b""

        wait_for(lambda: client.get(f"/api/catalog/catalogs/{catalog_id}").status_code == 404)
        wait_for(lambda: client.get("/api/catalog/catalogs").json() == [])
        wait_for(lambda: schema_names(client, catalog_id) == [])
        wait_for(lambda: searches(client, "id") == [])


def test_delete_discards_a_schema_and_a_table(config_dir: Path) -> None:
    """Discarding children leaves the parent catalog in place."""
    with TestClient(create_app()) as client:
        catalog_id = create_tree(client)

        table = client.delete(f"/api/catalog/catalogs/{catalog_id}/schemas/sales/tables/orders")
        assert table.status_code == 204
        schema = client.delete(f"/api/catalog/catalogs/{catalog_id}/schemas/sales")
        assert schema.status_code == 204

        wait_for(lambda: schema_names(client, catalog_id) == [])
        wait_for(lambda: searches(client, "id") == [])
        assert client.get(f"/api/catalog/catalogs/{catalog_id}").status_code == 200


def test_empty_patch_is_rejected(config_dir: Path) -> None:
    """A patch without any field is a bad request."""
    with TestClient(create_app()) as client:
        catalog_id = create_tree(client)

        empty = client.patch(f"/api/catalog/catalogs/{catalog_id}", json={})

        assert empty.status_code == 400
        assert "name or description" in empty.json()["detail"]


def test_discarded_aggregates_reject_further_changes(config_dir: Path) -> None:
    """Changing a discarded catalog returns a conflict."""
    with TestClient(create_app()) as client:
        catalog_id = create_tree(client)
        assert client.delete(f"/api/catalog/catalogs/{catalog_id}").status_code == 204

        rejected = client.patch(
            f"/api/catalog/catalogs/{catalog_id}",
            json={"name": "warehouse"},
        )

        assert rejected.status_code == 409
        assert "discarded" in rejected.json()["detail"]


def test_deleting_an_unknown_aggregate_returns_404(config_dir: Path) -> None:
    """Discarding an aggregate that does not exist returns not found."""
    with TestClient(create_app()) as client:
        assert client.delete(f"/api/catalog/catalogs/{uuid4()}").status_code == 404
        missing_schema = client.delete(f"/api/catalog/catalogs/{uuid4()}/schemas/sales")
        assert missing_schema.status_code == 404


def test_children_can_be_addressed_by_id(config_dir: Path) -> None:
    """The ids the create routes return also address the child resources."""
    with TestClient(create_app()) as client:
        catalog_id = client.post("/api/catalog/catalogs", params={"name": "analytics"}).json()[
            "catalog_id"
        ]
        schema_id = client.post(
            f"/api/catalog/catalogs/{catalog_id}/schemas",
            params={"schema_name": "sales"},
        ).json()["schema_id"]

        created = client.post(
            f"/api/catalog/catalogs/{catalog_id}/schemas/{schema_id}/tables",
            params={"table_name": "test_table"},
        )
        assert created.status_code == 200
        table_id = created.json()["table_id"]

        field = client.post(
            f"/api/catalog/catalogs/{catalog_id}/schemas/{schema_id}/tables/{table_id}/fields",
            params={"field_name": "id", "data_type": "integer"},
        )
        assert field.status_code == 200

        wait_for(lambda: first_search(client, "test_table").get("table_name") == "test_table")

        assert first_search(client, "id")["table_name"] == "test_table"


def test_unknown_ids_are_not_found(config_dir: Path) -> None:
    """An id that is not registered in the parent answers 404."""
    with TestClient(create_app()) as client:
        catalog_id = client.post("/api/catalog/catalogs", params={"name": "analytics"}).json()[
            "catalog_id"
        ]

        missing = client.post(
            f"/api/catalog/catalogs/{catalog_id}/schemas/{uuid4()}/tables",
            params={"table_name": "test_table"},
        )

        assert missing.status_code == 404
        assert "does not exist" in missing.json()["detail"]
