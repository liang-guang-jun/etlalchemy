"""Tests for the Databricks source: client reuse, lean reads and level caching."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from etlalchemy.ingestion.adapters import databricks as databricks_module
from etlalchemy.ingestion.adapters.databricks import DatabricksSourceFactory
from etlalchemy.ingestion.aggregates.connection import SourceConnection
from etlalchemy.ingestion.ports.secrets import SecretValue


def connection(**overrides: Any) -> SourceConnection:
    """Returns a Databricks connection with sensible defaults."""
    values: dict[str, Any] = {
        "name": "warehouse",
        "kind": "databricks",
        "endpoint": "https://example.cloud.databricks.com",
        "credential_ref": "env:DBX_TOKEN",
    }
    values.update(overrides)
    return SourceConnection(**values)


@dataclass(frozen=True)
class FakeName:
    """Object with a name, like the rows the Unity Catalog lists return."""

    name: str


@dataclass(frozen=True)
class FakeColumn:
    """Column as reported by ``tables.get``."""

    name: str
    type_text: str | None
    type_name: str | None
    nullable: bool


class FakeApiClient:
    """Records whether the SDK client was closed."""

    def __init__(self, sdk: FakeSdk) -> None:
        self._sdk = sdk

    def close(self) -> None:
        self._sdk.closed.append(True)


class FakeCatalogApi:
    """Records ``catalogs.list`` calls."""

    def __init__(self, sdk: FakeSdk) -> None:
        self._sdk = sdk

    def list(self) -> list[FakeName]:
        self._sdk.calls.append(("catalogs.list", {}))
        return [FakeName(name) for name in self._sdk.catalogs]


class FakeSchemaApi:
    """Records ``schemas.list`` calls."""

    def __init__(self, sdk: FakeSdk) -> None:
        self._sdk = sdk

    def list(self, *, catalog_name: str, max_results: int | None = None) -> list[FakeName]:
        self._sdk.calls.append(
            ("schemas.list", {"catalog_name": catalog_name, "max_results": max_results})
        )
        return [FakeName(name) for name in self._sdk.schemas.get(catalog_name, [])]


class FakeTableApi:
    """Records ``tables.list`` and ``tables.get`` calls."""

    def __init__(self, sdk: FakeSdk) -> None:
        self._sdk = sdk

    def list(
        self,
        *,
        catalog_name: str,
        schema_name: str,
        max_results: int | None = None,
        omit_columns: bool = False,
        omit_properties: bool = False,
    ) -> list[FakeName]:
        self._sdk.calls.append(
            (
                "tables.list",
                {
                    "catalog_name": catalog_name,
                    "schema_name": schema_name,
                    "max_results": max_results,
                    "omit_columns": omit_columns,
                    "omit_properties": omit_properties,
                },
            )
        )
        return [
            FakeName(name)
            for name in self._sdk.tables.get((catalog_name, schema_name), [])
        ]

    def get(self, *, full_name: str) -> Any:
        self._sdk.calls.append(("tables.get", {"full_name": full_name}))
        return FakeTable(columns=self._sdk.columns.get(full_name, []))


@dataclass(frozen=True)
class FakeTable:
    """Table definition returned by ``tables.get``."""

    columns: list[FakeColumn]


class FakeClient:
    """Minimal ``WorkspaceClient`` stand-in."""

    def __init__(self, sdk: FakeSdk) -> None:
        self.api_client = FakeApiClient(sdk)
        self.catalogs = FakeCatalogApi(sdk)
        self.schemas = FakeSchemaApi(sdk)
        self.tables = FakeTableApi(sdk)


class FakeSdk:
    """Records the clients the factory builds and the calls they receive."""

    def __init__(self) -> None:
        self.client_kwargs: list[dict[str, Any]] = []
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.closed: list[bool] = []
        self.catalogs: list[str] = ["main"]
        self.schemas: dict[str, list[str]] = {"main": ["sales"]}
        self.tables: dict[tuple[str, str], list[str]] = {
            ("main", "sales"): ["orders", "items"],
        }
        self.columns: dict[str, list[FakeColumn]] = {
            "main.sales.orders": [
                FakeColumn(name="id", type_text="BIGINT", type_name=None, nullable=False),
                FakeColumn(name="tags", type_text=None, type_name="ARRAY<STRING>", nullable=True),
            ]
        }

    def client_class(self, **kwargs: Any) -> FakeClient:
        """Builds a fake client and records the constructor arguments."""
        self.client_kwargs.append(kwargs)
        return FakeClient(self)

    def count(self, operation: str) -> int:
        """Returns how often one SDK operation was called."""
        return sum(1 for name, _ in self.calls if name == operation)

    def kwargs_of(self, operation: str) -> dict[str, Any]:
        """Returns the arguments of the last call of one SDK operation."""
        for name, kwargs in reversed(self.calls):
            if name == operation:
                return kwargs
        raise AssertionError(f"{operation} was never called")


def install_fake_sdk(monkeypatch: pytest.MonkeyPatch) -> FakeSdk:
    """Replaces the lazily imported SDK client with the recording stub."""
    sdk = FakeSdk()
    monkeypatch.setattr(databricks_module, "_workspace_client_class", lambda: sdk.client_class)
    return sdk


async def test_the_client_is_reused_across_requests(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A second request for the same connection leases the cached client."""
    sdk = install_fake_sdk(monkeypatch)
    factory = DatabricksSourceFactory()

    first = await factory.build(connection(), SecretValue("dapi-token"))
    assert await first.list_catalogs() == ["main"]
    await first.close()

    second = await factory.build(connection(), SecretValue("dapi-token"))
    assert await second.list_catalogs() == ["main"]
    await second.close()

    assert len(sdk.client_kwargs) == 1
    assert sdk.closed == []


async def test_a_rotated_token_opens_a_new_client(monkeypatch: pytest.MonkeyPatch) -> None:
    """The cache key follows the credential, so a rotation cannot reuse it."""
    sdk = install_fake_sdk(monkeypatch)
    factory = DatabricksSourceFactory()

    await factory.build(connection(), SecretValue("first"))
    await factory.build(connection(), SecretValue("second"))

    assert [kwargs["token"] for kwargs in sdk.client_kwargs] == ["first", "second"]


async def test_the_tables_level_asks_for_names_only(monkeypatch: pytest.MonkeyPatch) -> None:
    """The table names come without columns and properties."""
    sdk = install_fake_sdk(monkeypatch)
    factory = DatabricksSourceFactory()

    source = await factory.build(connection(), SecretValue("dapi-token"))
    assert await source.list_tables("main", "sales") == ["orders", "items"]

    assert sdk.kwargs_of("tables.list") == {
        "catalog_name": "main",
        "schema_name": "sales",
        "max_results": 200,
        "omit_columns": True,
        "omit_properties": True,
    }


async def test_the_page_size_follows_the_connection_option(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A connection may ask for bigger pages than the default."""
    sdk = install_fake_sdk(monkeypatch)
    factory = DatabricksSourceFactory()

    source = await factory.build(
        connection(options={"page_size": "500"}),
        SecretValue("dapi-token"),
    )
    await source.list_schemas("main")

    assert sdk.kwargs_of("schemas.list")["max_results"] == 500


async def test_levels_are_cached_until_the_ttl_expires(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A level is read once and refreshed after the configured TTL."""
    sdk = install_fake_sdk(monkeypatch)
    now = [1000.0]
    factory = DatabricksSourceFactory(clock=lambda: now[0])

    source = await factory.build(connection(), SecretValue("dapi-token"))
    assert await source.list_schemas("main") == ["sales"]
    assert await source.list_schemas("main") == ["sales"]
    assert sdk.count("schemas.list") == 1

    now[0] += 31
    assert await source.list_schemas("main") == ["sales"]
    assert sdk.count("schemas.list") == 2


async def test_the_metadata_cache_can_be_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """A TTL of zero reads every level from the source again."""
    sdk = install_fake_sdk(monkeypatch)
    factory = DatabricksSourceFactory()

    source = await factory.build(
        connection(options={"metadata_cache_ttl": "0"}),
        SecretValue("dapi-token"),
    )
    await source.list_schemas("main")
    await source.list_schemas("main")

    assert sdk.count("schemas.list") == 2


async def test_an_evicted_client_is_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    """The client cache stays bounded and releases what it drops."""
    sdk = install_fake_sdk(monkeypatch)
    factory = DatabricksSourceFactory()

    for index in range(9):
        source = await factory.build(
            connection(name=f"warehouse-{index}"),
            SecretValue(f"token-{index}"),
        )
        await source.close()

    assert len(sdk.client_kwargs) == 9
    assert sdk.closed == [True]


async def test_the_network_timeouts_reach_the_client(monkeypatch: pytest.MonkeyPatch) -> None:
    """Timeout options are passed to the SDK instead of being dropped."""
    sdk = install_fake_sdk(monkeypatch)
    factory = DatabricksSourceFactory()

    await factory.build(
        connection(
            options={"http_timeout_seconds": "30", "retry_timeout_seconds": "90"},
        ),
        SecretValue("dapi-token"),
    )

    assert sdk.client_kwargs == [
        {
            "host": "https://example.cloud.databricks.com",
            "token": "dapi-token",
            "http_timeout_seconds": 30,
            "retry_timeout_seconds": 90,
        }
    ]


async def test_one_table_reads_its_columns_in_a_single_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The column level is one ``tables.get`` and keeps the native types."""
    sdk = install_fake_sdk(monkeypatch)
    factory = DatabricksSourceFactory()

    source = await factory.build(connection(), SecretValue("dapi-token"))
    columns = await source.list_columns("main", "sales", "orders")

    assert sdk.kwargs_of("tables.get") == {"full_name": "main.sales.orders"}
    assert [(column.name, column.raw_type, column.nullable) for column in columns] == [
        ("id", "BIGINT", False),
        ("tags", "ARRAY<STRING>", True),
    ]
