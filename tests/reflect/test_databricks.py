"""Tests for Databricks connection detection."""

from __future__ import annotations

import builtins
from pathlib import Path
from types import SimpleNamespace

import etlalchemy.reflect.databricks as databricks
import pytest
from etlalchemy.reflect import ReflectSource

_ENVIRONMENT = (
    "DATABRICKS_RUNTIME_VERSION",
    "DATABRICKS_SERVER_HOSTNAME",
    "DATABRICKS_HOST",
    "DATABRICKS_HTTP_PATH",
    "DATABRICKS_TOKEN",
    "DATABRICKS_CLIENT_ID",
    "DATABRICKS_CLIENT_SECRET",
)


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Remove every Databricks variable and hide the CLI config file."""
    for name in _ENVIRONMENT:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(
        databricks,
        "_default_config_path",
        lambda: tmp_path / "missing-databrickscfg",
    )
    monkeypatch.delattr(builtins, "dbutils", raising=False)
    monkeypatch.delattr(builtins, "spark", raising=False)


def test_connection_url_is_returned_unchanged() -> None:
    """An explicit URL wins over every other detection path."""
    source = ReflectSource(connection_url="sqlite:///shop.db")

    url, connect_args = databricks.databricks_connection(source)

    assert url == "sqlite:///shop.db"
    assert connect_args == {}


def test_runtime_environment_builds_a_tokenless_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A notebook runtime uses the server hostname and the HTTP path."""
    monkeypatch.setenv("DATABRICKS_RUNTIME_VERSION", "15.4")
    monkeypatch.setenv("DATABRICKS_SERVER_HOSTNAME", "adb-123.azuredatabricks.net")
    monkeypatch.setenv("DATABRICKS_HTTP_PATH", "/sql/1.0/warehouses/abc")

    url, _ = databricks.databricks_connection(ReflectSource())

    assert url == (
        "databricks://adb-123.azuredatabricks.net:443"
        "?http_path=/sql/1.0/warehouses/abc"
    )


def test_runtime_environment_without_http_path_has_no_query(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A runtime that advertises no warehouse keeps a plain URL."""
    monkeypatch.setenv("DATABRICKS_RUNTIME_VERSION", "15.4")
    monkeypatch.setenv("DATABRICKS_SERVER_HOSTNAME", "adb-123.azuredatabricks.net")

    url, _ = databricks.databricks_connection(ReflectSource())

    assert url == "databricks://adb-123.azuredatabricks.net:443"


def test_environment_token_builds_a_token_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A server hostname and a token are enough outside a runtime."""
    monkeypatch.setenv("DATABRICKS_SERVER_HOSTNAME", "adb-123.azuredatabricks.net")
    monkeypatch.setenv("DATABRICKS_TOKEN", "dapi-secret")

    url, _ = databricks.databricks_connection(ReflectSource())

    assert url == ("databricks://token:dapi-secret@adb-123.azuredatabricks.net:443")


def test_undetectable_source_raises_the_detection_error() -> None:
    """With no URL, profile, runtime, variables or profile the call fails."""
    with pytest.raises(ValueError, match=databricks.DETECTION_MESSAGE):
        databricks.databricks_connection(ReflectSource())


class _FakeConfig:
    """Stand in for a Databricks SDK config."""

    def __init__(
        self,
        token: str | None = None,
        bearer: str | None = None,
        http_path: str | None = None,
    ) -> None:
        """Set the static token, the bearer and the configured HTTP path."""
        self.host = "https://adb-123.azuredatabricks.net/"
        self.token = token
        self.http_path = http_path
        self._bearer = bearer
        self.authenticated = False

    def authenticate(self) -> dict[str, str]:
        """Return an Authorization header, or nothing."""
        self.authenticated = True
        if self._bearer is None:
            return {}
        return {"Authorization": f"Bearer {self._bearer}"}


@pytest.fixture(autouse=True)
def no_warehouse_lookup(monkeypatch: pytest.MonkeyPatch) -> None:
    """Never ask the workspace for warehouses from a unit test."""
    monkeypatch.setattr(databricks, "_first_warehouse_path", lambda profile: "")


def test_cli_profile_uses_the_authenticated_bearer_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A CLI profile stores no token, so the auth strategy supplies one."""
    config = _FakeConfig(bearer="oauth-token")
    monkeypatch.setattr(databricks, "_sdk_config", lambda profile, **kwargs: config)

    url, _ = databricks.databricks_connection(ReflectSource(profile="DEFAULT"))

    assert url == "databricks://token:oauth-token@adb-123.azuredatabricks.net:443"
    assert config.authenticated is True


def test_profile_keeps_the_configured_http_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A profile with a warehouse path does not need a lookup."""
    config = _FakeConfig(token="dapi-static", http_path="/sql/1.0/warehouses/abc")
    monkeypatch.setattr(databricks, "_sdk_config", lambda profile, **kwargs: config)

    def fail(profile: str) -> str:
        raise AssertionError("the configured warehouse path wins")

    monkeypatch.setattr(databricks, "_first_warehouse_path", fail)

    url, _ = databricks.databricks_connection(ReflectSource(profile="DEFAULT"))

    assert url == (
        "databricks://token:dapi-static@adb-123.azuredatabricks.net:443"
        "?http_path=/sql/1.0/warehouses/abc"
    )


def test_profile_without_http_path_discovers_a_warehouse(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``databricks auth login`` stores no warehouse, so the SDK finds one."""
    config = _FakeConfig(bearer="oauth-token")
    monkeypatch.setattr(databricks, "_sdk_config", lambda profile, **kwargs: config)
    monkeypatch.setattr(
        databricks,
        "_first_warehouse_path",
        lambda profile: "/sql/1.0/warehouses/discovered",
    )

    url, _ = databricks.databricks_connection(ReflectSource(profile="DEFAULT"))

    assert url == (
        "databricks://token:oauth-token@adb-123.azuredatabricks.net:443"
        "?http_path=/sql/1.0/warehouses/discovered"
    )


def test_static_profile_token_skips_authentication(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A profile with a token in the config never runs the auth strategy."""
    config = _FakeConfig(token="dapi-static")
    monkeypatch.setattr(databricks, "_sdk_config", lambda profile, **kwargs: config)

    url, _ = databricks.databricks_connection(ReflectSource(profile="DEFAULT"))

    assert url == "databricks://token:dapi-static@adb-123.azuredatabricks.net:443"
    assert config.authenticated is False


def test_profile_without_any_credentials_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An auth strategy that returns no bearer token is a detection failure."""
    config = _FakeConfig()
    monkeypatch.setattr(databricks, "_sdk_config", lambda profile, **kwargs: config)

    with pytest.raises(ValueError, match=databricks.DETECTION_MESSAGE):
        databricks.databricks_connection(ReflectSource(profile="DEFAULT"))


def _fake_dbutils(host: str, token: str) -> object:
    """Build the ``dbutils`` chain a Databricks notebook exposes."""
    context = SimpleNamespace(
        browserHostName=lambda: SimpleNamespace(get=lambda: host),
        apiToken=lambda: SimpleNamespace(get=lambda: token),
    )
    return SimpleNamespace(
        notebook=SimpleNamespace(
            entry_point=SimpleNamespace(
                getDbutils=lambda: SimpleNamespace(
                    notebook=lambda: SimpleNamespace(getContext=lambda: context)
                )
            )
        )
    )


def _fake_spark(conf: dict[str, str]) -> object:
    """Build a ``spark`` object that answers ``conf.get`` from a dict."""
    return SimpleNamespace(conf=SimpleNamespace(get=conf.get))


def test_notebook_context_is_detected_with_the_warehouse_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The notebook runtime supplies host, token and the SQL warehouse path."""
    monkeypatch.setattr(
        builtins,
        "dbutils",
        _fake_dbutils("adb-123.azuredatabricks.net", "dapi-from-notebook"),
        raising=False,
    )
    monkeypatch.setattr(
        builtins,
        "spark",
        _fake_spark(
            {"spark.databricks.service.server.httpPath": "/sql/1.0/warehouses/abc"}
        ),
        raising=False,
    )

    url, _ = databricks.databricks_connection(ReflectSource())

    assert url == (
        "databricks://token:dapi-from-notebook@adb-123.azuredatabricks.net:443"
        "?http_path=/sql/1.0/warehouses/abc"
    )


def test_notebook_context_falls_back_to_the_cluster_sql_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An all-purpose cluster without a warehouse path uses its own endpoint."""
    monkeypatch.setattr(
        builtins,
        "dbutils",
        _fake_dbutils("adb-123.azuredatabricks.net", "dapi-from-notebook"),
        raising=False,
    )
    monkeypatch.setattr(
        builtins,
        "spark",
        _fake_spark(
            {
                "spark.databricks.clusterUsageTags.clusterId": "0815-120000-abc",
                "spark.databricks.clusterUsageTags.clusterOwnerOrgId": "1234",
            }
        ),
        raising=False,
    )

    url, _ = databricks.databricks_connection(ReflectSource())

    assert url == (
        "databricks://token:dapi-from-notebook@adb-123.azuredatabricks.net:443"
        "?http_path=/sql/protocolv1/o/1234/0815-120000-abc"
    )


def test_notebook_context_without_spark_has_no_http_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without Spark the URL carries the token but no warehouse path."""
    monkeypatch.setattr(
        builtins,
        "dbutils",
        _fake_dbutils("adb-123.azuredatabricks.net", "dapi-from-notebook"),
        raising=False,
    )

    url, _ = databricks.databricks_connection(ReflectSource())

    assert url == "databricks://token:dapi-from-notebook@adb-123.azuredatabricks.net:443"


def test_detection_falls_through_without_dbutils(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Outside a notebook the environment variables are still detected."""
    monkeypatch.setenv("DATABRICKS_SERVER_HOSTNAME", "adb-123.azuredatabricks.net")
    monkeypatch.setenv("DATABRICKS_TOKEN", "dapi-secret")

    url, _ = databricks.databricks_connection(ReflectSource())

    assert url == "databricks://token:dapi-secret@adb-123.azuredatabricks.net:443"


def test_a_broken_notebook_context_does_not_break_detection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A dbutils object without a notebook entry point is ignored."""
    monkeypatch.setattr(builtins, "dbutils", SimpleNamespace(), raising=False)

    with pytest.raises(ValueError, match=databricks.DETECTION_MESSAGE):
        databricks.databricks_connection(ReflectSource())


def test_notebook_detection_is_none_without_the_runtime() -> None:
    """Outside a notebook the helper reports no context at all."""
    assert databricks._detect_notebook_context() is None
