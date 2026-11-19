"""Tests for reading catalog resources addressed by name or id."""

import time
from collections.abc import Callable
from pathlib import Path
from typing import Any
from uuid import uuid4

from etlalchemy.app.api.app import create_app
from fastapi.testclient import TestClient

WAIT_TIMEOUT = 10.0


def wait_for(predicate: Callable[[], Any], timeout: float = WAIT_TIMEOUT) -> None:
    """Polls ``predicate`` until it returns a truthy value."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.05)
    raise AssertionError("timed out waiting for the projection")


def create_tree(client: TestClient) -> tuple[str, str, str]:
    """Creates a catalog, a schema, a table and a field, returning the ids."""
    catalog_id = client.post("/catalog/catalogs", params={"name": "analytics"}).json()[
        "catalog_id"
    ]
    schema_id = client.post(
        f"/catalog/catalogs/{catalog_id}/schemas",
        params={"schema_name": "sales", "description": "Sales data"},
    ).json()["schema_id"]
    table_id = client.post(
        f"/catalog/catalogs/{catalog_id}/schemas/sales/tables",
        params={"table_name": "orders"},
    ).json()["table_id"]
    client.post(
        f"/catalog/catalogs/{catalog_id}/schemas/sales/tables/orders/fields",
        params={"field_name": "id", "data_type": "integer", "nullable": False},
    )
    fields_url = f"/catalog/catalogs/{catalog_id}/schemas/{schema_id}/tables/{table_id}/fields"

    def field_visible() -> bool:
        response = client.get(fields_url)
        return response.status_code == 200 and bool(response.json())

    wait_for(field_visible)
    return catalog_id, schema_id, table_id


def test_children_are_readable_by_name_and_id(config_dir: Path) -> None:
    """Every read answers the same payload for a name and for an id."""
    with TestClient(create_app()) as client:
        catalog_id, schema_id, table_id = create_tree(client)

        by_name = client.get(f"/catalog/catalogs/{catalog_id}/schemas/sales").json()
        by_id = client.get(f"/catalog/catalogs/{catalog_id}/schemas/{schema_id}").json()
        assert by_name == by_id
        assert (by_name["schema_id"], by_name["name"]) == (schema_id, "sales")
        assert by_name["description"] == "Sales data"

        tables_by_name = client.get(
            f"/catalog/catalogs/{catalog_id}/schemas/sales/tables"
        ).json()
        tables_by_id = client.get(
            f"/catalog/catalogs/{catalog_id}/schemas/{schema_id}/tables"
        ).json()
        assert tables_by_name == tables_by_id
        assert [(row["table_id"], row["name"]) for row in tables_by_id] == [
            (table_id, "orders")
        ]

        table_by_name = client.get(
            f"/catalog/catalogs/{catalog_id}/schemas/sales/tables/orders"
        ).json()
        table_by_id = client.get(
            f"/catalog/catalogs/{catalog_id}/schemas/{schema_id}/tables/{table_id}"
        ).json()
        assert table_by_name == table_by_id
        assert table_by_id["table_id"] == table_id

        fields_by_name = client.get(
            f"/catalog/catalogs/{catalog_id}/schemas/sales/tables/orders/fields"
        ).json()
        fields_by_id = client.get(
            f"/catalog/catalogs/{catalog_id}/schemas/{schema_id}/tables/{table_id}/fields"
        ).json()
        assert fields_by_name == fields_by_id
        assert [(row["name"], row["data_type"], row["nullable"]) for row in fields_by_id] == [
            ("id", "integer", False)
        ]


def test_ids_stay_addressable_after_a_rename(config_dir: Path) -> None:
    """A renamed schema or table is still reachable through its id."""
    with TestClient(create_app()) as client:
        catalog_id, schema_id, table_id = create_tree(client)

        schema = client.patch(
            f"/catalog/catalogs/{catalog_id}/schemas/sales",
            json={"name": "revenue"},
        )
        assert schema.status_code == 200
        wait_for(
            lambda: client.get(
                f"/catalog/catalogs/{catalog_id}/schemas/{schema_id}"
            ).json().get("name")
            == "revenue"
        )

        table = client.patch(
            f"/catalog/catalogs/{catalog_id}/schemas/revenue/tables/orders",
            json={"name": "purchases"},
        )
        assert table.status_code == 200
        wait_for(
            lambda: client.get(
                f"/catalog/catalogs/{catalog_id}/schemas/{schema_id}/tables/{table_id}"
            ).json().get("name")
            == "purchases"
        )

        assert client.get(f"/catalog/catalogs/{catalog_id}/schemas/sales").status_code == 404
        assert (
            client.get(f"/catalog/catalogs/{catalog_id}/schemas/revenue/tables/orders").status_code
            == 404
        )
        renamed_table = client.get(
            f"/catalog/catalogs/{catalog_id}/schemas/{schema_id}/tables/{table_id}"
        ).json()
        assert renamed_table["name"] == "purchases"
        assert renamed_table["schema_id"] == schema_id


def test_unknown_references_are_not_found(config_dir: Path) -> None:
    """Unknown names, unknown ids and foreign children answer 404."""
    with TestClient(create_app()) as client:
        catalog_id, schema_id, table_id = create_tree(client)
        other_catalog = client.post("/catalog/catalogs", params={"name": "other"}).json()[
            "catalog_id"
        ]

        assert client.get(f"/catalog/catalogs/{catalog_id}/schemas/warehouse").status_code == 404
        assert client.get(f"/catalog/catalogs/{catalog_id}/schemas/{uuid4()}").status_code == 404
        assert (
            client.get(
                f"/catalog/catalogs/{catalog_id}/schemas/sales/tables/customers"
            ).status_code
            == 404
        )
        assert (
            client.get(f"/catalog/catalogs/{catalog_id}/schemas/sales/tables/{uuid4()}").status_code
            == 404
        )
        assert (
            client.get(f"/catalog/catalogs/{other_catalog}/schemas/{schema_id}").status_code == 404
        )
        assert (
            client.get(
                f"/catalog/catalogs/{catalog_id}/schemas/revenue/tables/{table_id}"
            ).status_code
            == 404
        )


def test_discarded_children_are_not_readable(config_dir: Path) -> None:
    """A discarded schema or table is hidden from the read endpoints."""
    with TestClient(create_app()) as client:
        catalog_id, schema_id, table_id = create_tree(client)

        assert (
            client.delete(
                f"/catalog/catalogs/{catalog_id}/schemas/{schema_id}/tables/{table_id}"
            ).status_code
            == 204
        )
        wait_for(
            lambda: client.get(
                f"/catalog/catalogs/{catalog_id}/schemas/{schema_id}/tables/{table_id}"
            ).status_code
            == 404
        )
        assert (
            client.get(f"/catalog/catalogs/{catalog_id}/schemas/sales/tables").json() == []
        )
        assert client.get(f"/catalog/catalogs/{catalog_id}/schemas/{schema_id}").status_code == 200

        assert client.delete(f"/catalog/catalogs/{catalog_id}/schemas/{schema_id}").status_code == 204
        wait_for(
            lambda: client.get(f"/catalog/catalogs/{catalog_id}/schemas/{schema_id}").status_code
            == 404
        )
        assert client.get(f"/catalog/catalogs/{catalog_id}/schemas/sales").status_code == 404
