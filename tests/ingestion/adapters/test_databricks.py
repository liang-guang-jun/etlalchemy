"""Tests for the Databricks type mapper and source factory."""

from typing import Any

import pytest

from etlalchemy.catalog.aggregates.types import DataType
from etlalchemy.ingestion.adapters import databricks as databricks_module
from etlalchemy.ingestion.adapters.databricks import (
    DatabricksSourceFactory,
    DatabricksTypeMapper,
)
from etlalchemy.ingestion.aggregates.connection import SourceConnection
from etlalchemy.ingestion.aggregates.errors import (
    MissingCredentialError,
    UnsupportedTypeError,
)
from etlalchemy.ingestion.ports.data_source import SourceProfile
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


def fake_client(
    monkeypatch: pytest.MonkeyPatch,
    calls: list[dict[str, Any]],
) -> None:
    """Replaces the lazily imported SDK client with a recording stub."""

    class FakeWorkspaceClient:
        def __init__(self, **kwargs: Any) -> None:
            calls.append(kwargs)

    monkeypatch.setattr(
        databricks_module,
        "_workspace_client_class",
        lambda: FakeWorkspaceClient,
    )


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("STRING", "string"),
        ("INT", "integer"),
        ("BIGINT", "bigint"),
        ("TINYINT", "smallint"),
        ("DOUBLE", "double"),
        ("BOOLEAN", "boolean"),
        ("TIMESTAMP_NTZ", "timestamp"),
    ],
)
def test_simple_types_are_mapped(raw: str, expected: str) -> None:
    """Known simple types map onto the catalog vocabulary."""
    assert DatabricksTypeMapper().map(raw) == DataType.parse(expected)


def test_parameterized_types_are_mapped() -> None:
    """Decimal, varchar and char keep their parameters."""
    mapper = DatabricksTypeMapper()

    assert mapper.map("DECIMAL(10,2)") == DataType.parse("decimal(10,2)")
    assert mapper.map("DECIMAL(10)") == DataType.parse("decimal(10,0)")
    assert mapper.map("VARCHAR(255)") == DataType.parse("varchar(255)")


def test_unsupported_types_follow_the_policy() -> None:
    """Unsupported types fail, become json or are skipped as configured."""
    with pytest.raises(UnsupportedTypeError, match="ARRAY"):
        DatabricksTypeMapper().map("ARRAY<STRING>")

    assert DatabricksTypeMapper("json").map("ARRAY<STRING>") == DataType.parse("json")
    assert DatabricksTypeMapper("skip").map("ARRAY<STRING>") is None


async def test_a_token_connection_passes_only_host_and_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A stored credential builds the client without unsupported keywords.

    ``warehouse_id`` is not a ``WorkspaceClient`` parameter, so an option that
    carries it must not leak into the constructor call.
    """
    calls: list[dict[str, Any]] = []
    fake_client(monkeypatch, calls)

    await DatabricksSourceFactory().build(
        connection(options={"warehouse_id": "abc"}),
        SecretValue("dapi-token"),
    )

    assert calls == [
        {"host": "https://example.cloud.databricks.com", "token": "dapi-token"}
    ]


async def test_a_profile_connection_uses_the_profile_and_endpoint_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A profile supplies the credentials; a non-blank endpoint overrides the host."""
    calls: list[dict[str, Any]] = []
    fake_client(monkeypatch, calls)

    await DatabricksSourceFactory().build(
        connection(endpoint="https://override.test", credential_ref="profile:team"),
        None,
    )

    assert calls == [{"profile": "team", "host": "https://override.test"}]


async def test_a_profile_connection_without_endpoint_lets_the_profile_win(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An empty endpoint keeps the host recorded in the CLI profile."""
    calls: list[dict[str, Any]] = []
    fake_client(monkeypatch, calls)

    await DatabricksSourceFactory().build(
        connection(endpoint="", credential_ref="profile:"),
        None,
    )

    assert calls == [{"profile": None}]


async def test_a_token_connection_without_a_secret_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A non-profile connection cannot be built without a resolved secret."""
    calls: list[dict[str, Any]] = []
    fake_client(monkeypatch, calls)

    with pytest.raises(MissingCredentialError):
        await DatabricksSourceFactory().build(connection(), None)

    assert calls == []


async def test_profiles_are_read_from_the_local_cli_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The factory exposes the profiles of the machine."""
    profiles = [SourceProfile(name="DEFAULT", host="https://example.test")]
    monkeypatch.setattr(databricks_module, "read_profiles", lambda: profiles)

    assert await DatabricksSourceFactory().list_profiles() == profiles
