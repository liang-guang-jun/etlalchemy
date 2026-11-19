"""Tests for the vocabulary HTTP routes."""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from etlalchemy.app.api.app import create_app
from fastapi.testclient import TestClient

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


def create_tree(client: TestClient) -> tuple[str, str, str, str]:
    """Creates finance/Revenue, Revenue/ARR and Revenue/ARR/MRR."""
    domain = client.post("/vocabulary/domains", json={"name": "finance"})
    assert domain.status_code == 201
    domain_id = domain.json()["domain_id"]
    base = f"/vocabulary/domains/{domain_id}/terms"

    root = client.post(base, json={"name": "Revenue", "definition": "Recognized revenue"})
    assert root.status_code == 201
    root_id = root.json()["term_id"]
    arr = client.post(
        base,
        json={"name": "ARR", "definition": "Annual recurring revenue", "parent": "Revenue"},
    )
    assert arr.status_code == 201
    arr_id = arr.json()["term_id"]
    mrr = client.post(
        base,
        json={"name": "MRR", "definition": "Monthly recurring revenue", "parent": "Revenue/ARR"},
    )
    assert mrr.status_code == 201
    mrr_id = mrr.json()["term_id"]

    wait_for(lambda: client.get(f"{base}/{root_id}").status_code == 200)

    def paths_ready() -> bool:
        rows = client.get(base).json()
        return {row["path"] for row in rows} == {"Revenue", "Revenue/ARR", "Revenue/ARR/MRR"}

    wait_for(paths_ready)
    return domain_id, root_id, arr_id, mrr_id


def create_catalog_field(client: TestClient) -> tuple[str, str]:
    """Creates a catalog, schema, table and field, returning the table id."""
    catalog = client.post("/catalog/catalogs", params={"name": "analytics"})
    assert catalog.status_code == 200
    catalog_id = catalog.json()["catalog_id"]
    assert (
        client.post(
            f"/catalog/catalogs/{catalog_id}/schemas",
            params={"schema_name": "sales"},
        ).status_code
        == 200
    )
    table = client.post(
        f"/catalog/catalogs/{catalog_id}/schemas/sales/tables",
        params={"table_name": "orders"},
    )
    assert table.status_code == 200
    table_id = table.json()["table_id"]
    assert (
        client.post(
            f"/catalog/catalogs/{catalog_id}/schemas/sales/tables/orders/fields",
            params={"field_name": "customer_id", "data_type": "integer", "nullable": False},
        ).status_code
        == 200
    )
    fields_url = f"/catalog/catalogs/{catalog_id}/schemas/sales/tables/orders/fields"

    def field_visible() -> bool:
        response = client.get(fields_url)
        return response.status_code == 200 and bool(response.json())

    wait_for(field_visible)
    return catalog_id, table_id


def test_domain_and_tree_roundtrip(config_dir: Path) -> None:
    """The nested tree supports create, list, children and detail reads."""
    app = create_app()
    with TestClient(app) as client:
        domain_id, root_id, arr_id, mrr_id = create_tree(client)
        base = f"/vocabulary/domains/{domain_id}/terms"

        rows = client.get(base).json()
        assert [(row["path"], row["parent_id"]) for row in rows] == [
            ("Revenue", None),
            ("Revenue/ARR", root_id),
            ("Revenue/ARR/MRR", arr_id),
        ]
        assert [row["term_id"] for row in client.get(
            f"/vocabulary/domains/{domain_id}/children"
        ).json()] == [root_id]
        assert [row["term_id"] for row in client.get(
            f"/vocabulary/domains/{domain_id}/children", params={"parent": "Revenue"}
        ).json()] == [arr_id]
        assert [row["term_id"] for row in client.get(
            f"{base}/{root_id}/descendants"
        ).json()] == [arr_id, mrr_id]

        detail = client.get(f"{base}/{mrr_id}").json()
        assert (detail["name"], detail["path"]) == ("MRR", "Revenue/ARR/MRR")
        assert detail["aliases"] == []
        assert detail["links"] == []


def test_rename_and_move_repath_the_subtree(config_dir: Path) -> None:
    """Renaming or moving a parent renames every descendant path."""
    app = create_app()
    with TestClient(app) as client:
        domain_id, root_id, arr_id, mrr_id = create_tree(client)
        base = f"/vocabulary/domains/{domain_id}/terms"

        assert client.patch(f"{base}/{root_id}", json={"name": "Sales"}).status_code == 200

        def renamed() -> bool:
            return client.get(f"{base}/{mrr_id}").json()["path"] == "Sales/ARR/MRR"

        wait_for(renamed)
        assert client.get(f"{base}/{arr_id}").json()["path"] == "Sales/ARR"

        moved = client.post(f"{base}/{mrr_id}/move", json={"new_parent": None})
        assert moved.status_code == 200

        def moved_ready() -> bool:
            return client.get(f"{base}/{mrr_id}").json()["path"] == "MRR"

        wait_for(moved_ready)
        assert client.get(f"{base}/{mrr_id}").json()["parent_id"] is None


def test_cycle_duplicate_and_invalid_names_are_rejected(config_dir: Path) -> None:
    """A cycle answers 409, as do duplicate paths and invalid names."""
    app = create_app()
    with TestClient(app) as client:
        domain_id, root_id, _, _ = create_tree(client)
        base = f"/vocabulary/domains/{domain_id}/terms"

        assert (
            client.post(f"{base}/{root_id}/move", json={"new_parent": "Revenue/ARR"}).status_code
            == 409
        )
        assert client.post(base, json={"name": "Revenue", "definition": "dup"}).status_code == 409
        assert client.post(base, json={"name": " ", "definition": "blank"}).status_code == 409
        assert client.post(base, json={"name": "A/B", "definition": "slash"}).status_code == 409
        assert (
            client.post(base, json={"name": "Forecast", "definition": "x", "parent": "Missing"}).status_code
            == 404
        )
        assert client.patch(f"{base}/{root_id}", json={}).status_code == 400
        assert client.get(f"{base}/00000000-0000-0000-0000-000000000000").status_code == 404


def test_status_flow_and_links(config_dir: Path) -> None:
    """The status machine and the catalog links are exposed over HTTP."""
    app = create_app()
    with TestClient(app) as client:
        domain_id, _, arr_id, _ = create_tree(client)
        _, table_id = create_catalog_field(client)
        base = f"/vocabulary/domains/{domain_id}/terms"

        assert client.post(f"{base}/{arr_id}/links", params={
            "target_id": table_id,
            "target_kind": "field",
            "field_name": "customer_id",
        }).status_code == 204
        links = wait_for(lambda: client.get(f"{base}/{arr_id}").json()["links"])
        assert [(link["target_kind"], link["field_name"]) for link in links] == [
            ("field", "customer_id")
        ]
        assert [(link["status"], link["target_name"]) for link in links] == [
            ("resolved", "orders.customer_id")
        ]

        for url, params in (
            (
                "/vocabulary/terms-for-target",
                {
                    "target_id": table_id,
                    "target_kind": "field",
                    "field_name": "customer_id",
                },
            ),
            ("/vocabulary/terms-for-table", {"table_id": table_id}),
            (
                "/vocabulary/terms-for-field",
                {"table_id": table_id, "field_name": "customer_id"},
            ),
        ):
            rows = client.get(url, params=params).json()
            assert [row["term_id"] for row in rows] == [arr_id]

        assert client.post(f"{base}/{arr_id}/approve", params={"reviewer": "alice"}).status_code == 200
        assert client.patch(f"{base}/{arr_id}", json={"definition": "changed"}).status_code == 409
        assert client.post(f"{base}/{arr_id}/reopen").status_code == 200
        assert client.patch(f"{base}/{arr_id}", json={"definition": "changed"}).status_code == 200
        assert client.post(f"{base}/{arr_id}/approve").status_code == 200
        assert client.post(f"{base}/{arr_id}/deprecate").status_code == 200
        assert client.post(f"{base}/{arr_id}/reactivate").status_code == 200

        assert client.delete(f"{base}/{arr_id}/links", params={
            "target_id": table_id,
            "target_kind": "field",
            "field_name": "customer_id",
        }).status_code == 204
        wait_for(lambda: client.get(f"{base}/{arr_id}").json()["links"] == [])


def test_search_and_discard_cascade(config_dir: Path) -> None:
    """Search finds by alias, and discarding a parent removes the subtree."""
    app = create_app()
    with TestClient(app) as client:
        domain_id, root_id, arr_id, mrr_id = create_tree(client)
        base = f"/vocabulary/domains/{domain_id}/terms"

        assert client.patch(
            f"{base}/{arr_id}",
            json={"aliases_add": ["annual recurring revenue"]},
        ).status_code == 200

        def alias_indexed() -> list[dict[str, Any]] | None:
            rows = client.get("/vocabulary/search", params={"q": "annual"}).json()
            if rows and rows[0]["matched_alias"] == "annual recurring revenue":
                return rows
            return None

        results = wait_for(alias_indexed)
        assert [(row["term_id"], row["matched_alias"]) for row in results] == [
            (arr_id, "annual recurring revenue")
        ]

        assert client.delete(f"{base}/{root_id}").status_code == 204
        wait_for(lambda: client.get(base).json() == [])
        assert client.get(f"{base}/{mrr_id}").status_code == 404
        assert client.get(f"/vocabulary/domains/{domain_id}").status_code == 200


def test_term_colour_roundtrip(config_dir: Path) -> None:
    """A colour can be set on create, patched on any status and cleared."""
    app = create_app()
    with TestClient(app) as client:
        domain_id, root_id, arr_id, _ = create_tree(client)
        base = f"/vocabulary/domains/{domain_id}/terms"

        coloured = client.post(base, json={"name": "TCV", "definition": "Total", "color": "#F2C811"})
        assert coloured.status_code == 201
        coloured_id = coloured.json()["term_id"]

        detail = wait_for(
            lambda: (
                response
                if (response := client.get(f"{base}/{coloured_id}")).status_code == 200
                and response.json()["color"] == "#f2c811"
                else None
            )
        )
        assert detail.json()["color"] == "#f2c811"

        assert (
            client.patch(f"{base}/{coloured_id}", json={"color": "#aabbcc"}).status_code == 200
        )

        def patched() -> bool:
            return client.get(f"{base}/{coloured_id}").json()["color"] == "#aabbcc"

        wait_for(patched)

        # Colour is metadata, so an approved term keeps accepting changes.
        assert client.post(f"{base}/{arr_id}/approve").status_code == 200
        assert client.patch(f"{base}/{arr_id}", json={"color": "#6bb700"}).status_code == 200

        def approved_coloured() -> bool:
            return client.get(f"{base}/{arr_id}").json()["color"] == "#6bb700"

        wait_for(approved_coloured)

        assert client.patch(f"{base}/{root_id}", json={"color": ""}).status_code == 200
        listed = wait_for(
            lambda: [
                row for row in client.get(base).json() if row["term_id"] == coloured_id
            ]
            or None
        )
        assert listed[0]["color"] == "#aabbcc"


def test_invalid_term_colour_is_rejected(config_dir: Path) -> None:
    """A malformed colour answers 400 because InvalidColorError is a ValueError."""
    app = create_app()
    with TestClient(app) as client:
        domain_id, root_id, _, _ = create_tree(client)
        base = f"/vocabulary/domains/{domain_id}/terms"

        response = client.patch(f"{base}/{root_id}", json={"color": "amber"})

        assert response.status_code == 400
        assert "#f2c811" in response.json()["detail"]
