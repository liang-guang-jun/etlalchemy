"""Tests for the ingestion HTTP routes."""

import time
from collections.abc import Callable
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from dependency_injector import providers
from fastapi.testclient import TestClient

from etlalchemy.app.api.app import create_app
from etlalchemy.ingestion.ports.data_source import ColumnInfo, SourceProfile
from tests.ingestion.support import FakeSource, FakeSourceFactory

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


def run_or_none(client: TestClient, run_id: str) -> Any:
    """Returns one import run, or ``None`` while the projection catches up."""
    response = client.get(f"/api/ingestion/runs/{run_id}")
    return response.json() if response.status_code == 200 else None


def test_connection_crud_roundtrip(config_dir: Path) -> None:
    """Connections support create, list, get, patch, rotate and delete."""
    app = create_app()
    with TestClient(app) as client:
        created = client.post(
            "/api/ingestion/connections",
            json={
                "name": "warehouse",
                "kind": "databricks",
                "endpoint": "https://example.test",
                "credential_ref": "env:DBX_TOKEN",
                "default_catalog": "main",
                "options": {"warehouse_id": "abc"},
            },
        )
        assert created.status_code == 201
        connection_id = created.json()["connection_id"]

        rows = wait_for(lambda: client.get("/api/ingestion/connections").json())
        assert [row["name"] for row in rows] == ["warehouse"]
        assert rows[0]["credential_ref"] == "env:DBX_TOKEN"
        assert rows[0]["has_inline_credential"] is False
        assert rows[0]["options"] == {"warehouse_id": "abc"}

        fetched = client.get(f"/api/ingestion/connections/{connection_id}")
        assert fetched.status_code == 200
        assert fetched.json()["default_catalog"] == "main"

        patched = client.patch(
            f"/api/ingestion/connections/{connection_id}",
            json={"name": "renamed"},
        )
        assert patched.status_code == 200
        assert patched.json() == {"ok": True}
        wait_for(
            lambda: client.get("/api/ingestion/connections").json()[0]["name"] == "renamed"
        )

        rotated = client.post(
            f"/api/ingestion/connections/{connection_id}/rotate",
            json={"token": "s3cr3t"},
        )
        assert rotated.status_code == 200
        wait_for(
            lambda: client.get(f"/api/ingestion/connections/{connection_id}").json()[
                "has_inline_credential"
            ]
            is True
        )

        deleted = client.delete(f"/api/ingestion/connections/{connection_id}")
        assert deleted.status_code == 204
        wait_for(lambda: client.get("/api/ingestion/connections").json() == [])
        assert client.get(f"/api/ingestion/connections/{connection_id}").status_code == 404


def test_duplicate_connection_name_is_a_conflict(config_dir: Path) -> None:
    """Creating the same connection name twice answers 409."""
    app = create_app()
    body = {
        "name": "warehouse",
        "kind": "databricks",
        "endpoint": "https://example.test",
        "credential_ref": "env:DBX_TOKEN",
    }
    with TestClient(app) as client:
        assert client.post("/api/ingestion/connections", json=body).status_code == 201
        wait_for(lambda: client.get("/api/ingestion/connections").json())

        conflict = client.post("/api/ingestion/connections", json=body)

        assert conflict.status_code == 409
        assert "warehouse" in conflict.json()["detail"]


def test_unknown_kind_is_a_conflict_and_ambiguous_credential_is_rejected(
    config_dir: Path,
) -> None:
    """An unknown source kind is a conflict and both credentials are invalid."""
    app = create_app()
    with TestClient(app) as client:
        unknown = client.post(
            "/api/ingestion/connections",
            json={
                "name": "warehouse",
                "kind": "unknown",
                "endpoint": "https://example.test",
                "credential_ref": "env:DBX_TOKEN",
            },
        )
        assert unknown.status_code == 409
        assert "unknown" in unknown.json()["detail"]

        ambiguous = client.post(
            "/api/ingestion/connections",
            json={
                "name": "warehouse",
                "kind": "databricks",
                "endpoint": "https://example.test",
                "credential_ref": "env:DBX_TOKEN",
                "token": "s3cr3t",
            },
        )
        assert ambiguous.status_code == 422


def test_runs_are_listed_and_missing_ones_are_not_found(config_dir: Path) -> None:
    """Import runs are readable from the read model."""
    app = create_app()
    with TestClient(app) as client:
        assert client.get("/api/ingestion/runs").json() == []
        assert client.get(f"/api/ingestion/runs/{uuid4()}").status_code == 404
        assert (
            client.get("/api/ingestion/runs", params={"status": "failed"}).json() == []
        )


def test_import_unknown_connection_is_not_found(config_dir: Path) -> None:
    """Importing through an unknown connection answers 404."""
    app = create_app()
    with TestClient(app) as client:
        response = client.post(
            f"/api/ingestion/connections/{uuid4()}/import",
            json={"target_catalog_id": str(uuid4())},
        )

        assert response.status_code == 404


def test_import_endpoint_materialises_the_source(config_dir: Path) -> None:
    """A successful import writes the catalog tree and records the run."""
    source = FakeSource(
        catalogs={
            "src": {
                "sales": {
                    "orders": [
                        ColumnInfo(name="id", raw_type="BIGINT", nullable=False),
                        ColumnInfo(name="amount", raw_type="DECIMAL(10,2)", nullable=True),
                    ]
                }
            }
        }
    )
    factory = FakeSourceFactory(source)
    app = create_app()
    app.container.source_factories.override(providers.Object({"fake": factory}))

    with TestClient(app) as client:
        catalog_id = client.post(
            "/api/catalog/catalogs",
            params={"name": "target"},
        ).json()["catalog_id"]
        created = client.post(
            "/api/ingestion/connections",
            json={
                "name": "fake-source",
                "kind": "fake",
                "endpoint": "https://example.test",
                "token": "s3cr3t",
            },
        )
        assert created.status_code == 201
        connection_id = created.json()["connection_id"]

        imported = client.post(
            f"/api/ingestion/connections/{connection_id}/import",
            json={
                "target_catalog_id": catalog_id,
                "source_catalog": "src",
                "include_tables": {"sales": ["orders"]},
                "schema_mapping": {"sales": "sales_raw"},
            },
        )
        assert imported.status_code == 200
        run_id = imported.json()["run_id"]

        def finished() -> Any:
            row = run_or_none(client, run_id)
            return row if row is not None and row["status"] != "pending" else None

        run = wait_for(finished)
        assert run["status"] == "succeeded"
        assert (run["schema_count"], run["table_count"], run["field_count"]) == (1, 1, 2)

        # The catalog projection applies the imported fields one event at a
        # time, so wait for the whole set instead of the first non-empty answer.
        fields = wait_for(
            lambda: (
                rows
                if len(
                    rows := client.get(
                        f"/api/catalog/catalogs/{catalog_id}/schemas/sales_raw/tables/orders/fields"
                    ).json()
                )
                == 2
                else None
            )
        )
        assert [
            (row["name"], row["data_type"], row["nullable"]) for row in fields
        ] == [
            ("amount", "decimal(10,2)", True),
            ("id", "bigint", False),
        ]


def test_source_kinds_are_listed(config_dir: Path) -> None:
    """The configured source factories are advertised for the create dialog."""
    app = create_app()
    with TestClient(app) as client:
        response = client.get("/api/ingestion/source-kinds")

        assert response.status_code == 200
        kinds = [row["kind"] for row in response.json()]
        assert "databricks" in kinds


def test_a_profile_connection_omits_the_endpoint(config_dir: Path) -> None:
    """A profile reference supplies the host, so the endpoint may be empty."""
    app = create_app()
    with TestClient(app) as client:
        created = client.post(
            "/api/ingestion/connections",
            json={
                "name": "local",
                "kind": "databricks",
                "credential_ref": "profile:team",
            },
        )

        assert created.status_code == 201
        rows = wait_for(lambda: client.get("/api/ingestion/connections").json())
        assert rows[0]["credential_ref"] == "profile:team"
        assert rows[0]["endpoint"] == ""


def test_source_profiles_read_the_local_cli_config(
    config_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The profile list comes from the adapter without any secret."""
    monkeypatch.setattr(
        "etlalchemy.ingestion.adapters.databricks.read_profiles",
        lambda: [SourceProfile(name="team", host="https://example.test")],
    )
    app = create_app()
    with TestClient(app) as client:
        response = client.get("/api/ingestion/source-profiles", params={"kind": "databricks"})

        assert response.status_code == 200
        assert response.json() == [{"name": "team", "host": "https://example.test"}]
        unsupported = client.get("/api/ingestion/source-profiles", params={"kind": "postgres"})
        assert unsupported.status_code == 400


def _fake_connection(client: TestClient) -> str:
    """Creates a connection backed by a fake source and returns its id."""
    created = client.post(
        "/api/ingestion/connections",
        json={
            "name": "fake-source",
            "kind": "fake",
            "endpoint": "https://example.test",
            "token": "s3cr3t",
            "default_catalog": "src",
        },
    )
    assert created.status_code == 201
    connection_id: str = created.json()["connection_id"]
    return connection_id


def _fake_tree() -> FakeSource:
    """Builds a small source tree used by the inspection tests."""
    return FakeSource(
        catalogs={
            "src": {
                "sales": {
                    "orders": [
                        ColumnInfo(name="id", raw_type="BIGINT", nullable=False),
                        ColumnInfo(name="note", raw_type="unsupported", nullable=True),
                    ]
                }
            }
        }
    )


def test_inspect_walks_every_source_level(config_dir: Path) -> None:
    """Inspection answers catalogs, schemas, tables and columns in turn."""
    app = create_app()
    app.container.source_factories.override(
        providers.Object({"fake": FakeSourceFactory(_fake_tree())})
    )

    with TestClient(app) as client:
        connection_id = _fake_connection(client)
        base = f"/api/ingestion/connections/{connection_id}/inspect"

        catalogs = client.get(base)
        assert catalogs.status_code == 200
        assert catalogs.json() == {"node": "catalogs", "items": [{"name": "src"}]}

        schemas = client.get(base, params={"catalog": "src"})
        assert schemas.json() == {"node": "schemas", "items": [{"name": "sales"}]}

        tables = client.get(base, params={"catalog": "src", "schema": "sales"})
        assert tables.json() == {"node": "tables", "items": [{"name": "orders"}]}

        columns = client.get(
            base,
            params={"catalog": "src", "schema": "sales", "table": "orders"},
        )
        assert columns.json()["node"] == "columns"
        assert [(row["name"], row["mapped_type"]) for row in columns.json()["items"]] == [
            ("id", "bigint"),
            ("note", None),
        ]


def test_inspect_unknown_connection_is_not_found(config_dir: Path) -> None:
    """Inspecting a connection that does not exist answers 404."""
    app = create_app()
    with TestClient(app) as client:
        response = client.get(f"/api/ingestion/connections/{uuid4()}/inspect")

        assert response.status_code == 404


def test_plan_previews_the_import_without_writing(config_dir: Path) -> None:
    """A plan reports the diff and leaves the target catalog empty."""
    app = create_app()
    app.container.source_factories.override(
        providers.Object({"fake": FakeSourceFactory(_fake_tree())})
    )

    with TestClient(app) as client:
        catalog_id = client.post(
            "/api/catalog/catalogs",
            params={"name": "target"},
        ).json()["catalog_id"]
        connection_id = _fake_connection(client)

        planned = client.post(
            f"/api/ingestion/connections/{connection_id}/plan",
            json={
                "target_catalog_id": catalog_id,
                "source_catalog": "src",
                "schema_mapping": {"sales": "sales_raw"},
            },
        )

        assert planned.status_code == 200
        body = planned.json()
        assert (body["schema_count"], body["table_count"], body["field_count"]) == (1, 1, 1)
        assert body["new_schemas"] == ["sales_raw"]
        assert body["new_tables"] == ["sales_raw.orders"]
        assert body["unsupported_types"] == [
            {
                "table": "sales_raw.orders",
                "column": "note",
                "raw_type": "unsupported",
                "policy": "fail",
            }
        ]
        assert client.get(f"/api/catalog/catalogs/{catalog_id}/schemas").json() == []


def test_connection_test_reports_a_failing_source(config_dir: Path) -> None:
    """The probe answers ``ok`` with the error message of a broken source."""
    broken = _fake_tree()
    broken.fail_with = "boom"
    app = create_app()
    app.container.source_factories.override(
        providers.Object({"fake": FakeSourceFactory(broken)})
    )

    with TestClient(app) as client:
        connection_id = _fake_connection(client)

        response = client.post(f"/api/ingestion/connections/{connection_id}/test")

        assert response.status_code == 200
        assert response.json()["ok"] is False
        assert response.json()["error"] == "boom"
