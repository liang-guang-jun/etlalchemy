"""Resolve a Databricks SQLAlchemy URL from a reflection source.

The Databricks SDK is imported lazily, so the rest of the package does not
require it. Install ``etlalchemy[databricks]`` to use a CLI profile or the
client-credentials environment variables.

.. warning::
   The resolved URL carries the access token when one is available. Do not log
   it, and do not store it in a cache or a report.
"""

from __future__ import annotations

import builtins
import os
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from etlalchemy.reflect.source import ReflectSource

#: Message raised when no Databricks connection can be detected.
DETECTION_MESSAGE = (
    "No Databricks connection could be detected; pass connection_url or profile"
)

#: Port the SQLAlchemy Databricks dialect connects to.
_PORT = 443


@dataclass(frozen=True)
class _NotebookConnection:
    """Credentials and SQL endpoint resolved from a Databricks notebook."""

    host: str
    access_token: str
    http_path: str | None


def databricks_connection(
    source: ReflectSource,
) -> tuple[str, dict[str, object]]:
    """Return the SQLAlchemy URL and connect args for a Databricks source.

    ``connection_url`` is returned unchanged. Otherwise the URL is built from
    ``profile`` or, when ``auto_detect`` is set, from the notebook runtime, the
    ``DATABRICKS_*`` environment variables or the ``DEFAULT`` CLI profile.

    Args:
        source: Source whose Databricks connection should be resolved.

    Returns:
        The SQLAlchemy URL and the ``connect_args`` to pass to the engine.

    Raises:
        ValueError: If no connection can be detected.
        ImportError: If the Databricks SDK is needed but not installed.
    """
    if source.connection_url is not None:
        return source.connection_url, {}
    if source.profile is not None:
        host, token, http_path = _profile_credentials(source.profile)
        return _token_url(host, token, http_path), {}
    if source.auto_detect:
        detected = _detect_connection()
        if detected is not None:
            return detected, {}
    raise ValueError(DETECTION_MESSAGE)


def _detect_connection() -> str | None:
    """Return the auto-detected connection URL, or None.

    A Databricks notebook is asked first, because a cluster injects ``dbutils``
    and Spark regardless of whether the ``DATABRICKS_*`` variables are set.
    """
    notebook = _detect_notebook_context()
    if notebook is not None:
        return _token_url(notebook.host, notebook.access_token, notebook.http_path)

    runtime_version = os.environ.get("DATABRICKS_RUNTIME_VERSION")
    if runtime_version:
        host = os.environ.get("DATABRICKS_SERVER_HOSTNAME")
        http_path = os.environ.get("DATABRICKS_HTTP_PATH")
        if host:
            return _runtime_url(host, http_path)

    host = os.environ.get("DATABRICKS_SERVER_HOSTNAME") or os.environ.get(
        "DATABRICKS_HOST"
    )
    if host:
        token = os.environ.get("DATABRICKS_TOKEN")
        if not token:
            token = _client_credentials_token(host)
        if token:
            return _token_url(host, token, _path_from_env())

    if _default_config_path().is_file() and has_default_profile():
        return _default_profile_url()
    return None


def _runtime_global(name: str) -> object | None:
    """Read an injected notebook global without importing notebook modules."""
    value: object | None = getattr(builtins, name, None)
    if value is not None:
        return value
    main_module = sys.modules.get("__main__")
    if main_module is None:
        return None
    from_main: object | None = getattr(main_module, name, None)
    return from_main


def _spark_conf(spark: object | None, key: str) -> str | None:
    """Read one Spark configuration key when Spark is available."""
    if spark is None:
        return None
    conf = getattr(spark, "conf", None)
    getter = getattr(conf, "get", None)
    if not callable(getter):
        return None
    try:
        value = getter(key, None)
    except (AttributeError, TypeError, ValueError):
        return None
    return value if isinstance(value, str) and value else None


def _cluster_http_path(spark: object | None) -> str | None:
    """Build the classic cluster SQL endpoint when the warehouse path is absent."""
    cluster_id = _spark_conf(spark, "spark.databricks.clusterUsageTags.clusterId")
    organization_id = _spark_conf(
        spark,
        "spark.databricks.clusterUsageTags.clusterOwnerOrgId",
    )
    if cluster_id is None or organization_id is None:
        return None
    return f"/sql/protocolv1/o/{organization_id}/{cluster_id}"


def _detect_notebook_context() -> _NotebookConnection | None:
    """Return the notebook connection data, or None outside a notebook.

    ``dbutils.notebook.entry_point`` exposes the workspace host and a token,
    which is the only credential source on shared and serverless clusters.
    """
    dbutils = _runtime_global("dbutils")
    spark = _runtime_global("spark")
    if dbutils is None:
        return None
    try:
        notebook = getattr(dbutils, "notebook")
        entry_point = getattr(notebook, "entry_point")
        context = entry_point.getDbutils().notebook().getContext()
        host = context.browserHostName().get()
        access_token = context.apiToken().get()
    except (AttributeError, TypeError, ValueError):
        return None
    if not isinstance(host, str) or not host:
        return None
    if not isinstance(access_token, str) or not access_token:
        return None
    http_path = _spark_conf(spark, "spark.databricks.service.server.httpPath")
    http_path = http_path or _cluster_http_path(spark)
    return _NotebookConnection(
        host=host,
        access_token=access_token,
        http_path=http_path,
    )


def _profile_credentials(profile: str) -> tuple[str, str, str]:
    """Return the host, the token and the warehouse path of a CLI profile."""
    config = _sdk_config(profile)
    host = _require_host(config.host)
    return host, _require_token(config), _profile_http_path(profile, config)


def _profile_http_path(profile: str, config: object) -> str:
    """Return the warehouse path of a profile, discovering one when absent."""
    configured = getattr(config, "http_path", None)
    if isinstance(configured, str) and configured.strip():
        return _http_path(configured)
    return _first_warehouse_path(profile)


def _first_warehouse_path(profile: str) -> str:
    """Return the path of the first SQL warehouse of the workspace, if any.

    ``databricks auth login`` stores the host and the credentials but no
    warehouse, so the path is looked up through the SDK.
    """
    try:
        from databricks.sdk import WorkspaceClient
    except ImportError as exc:  # pragma: no cover - depends on the environment
        raise ImportError(
            "databricks-sdk is required to reflect Databricks tables; install "
            "etlalchemy[databricks]"
        ) from exc
    client = WorkspaceClient(profile=profile)
    for warehouse in client.warehouses.list():
        if warehouse.id:
            return _http_path(f"/sql/1.0/warehouses/{warehouse.id}")
    return ""


def _default_profile_url() -> str:
    """Return the URL of the ``DEFAULT`` profile of ``~/.databrickscfg``."""
    host, token, http_path = _profile_credentials("DEFAULT")
    return _token_url(host, token, http_path)


def _client_credentials_token(host: str) -> str | None:
    """Exchange client credentials for a token through the SDK."""
    client_id = os.environ.get("DATABRICKS_CLIENT_ID")
    client_secret = os.environ.get("DATABRICKS_CLIENT_SECRET")
    if not client_id or not client_secret:
        return None
    config = _sdk_config(
        None,
        host=host,
        client_id=client_id,
        client_secret=client_secret,
    )
    token = _optional_token(config) or _authenticated_token(config)
    if token:
        return token
    raise ValueError(DETECTION_MESSAGE)


def _sdk_config(profile: str | None, **kwargs: Any) -> Any:
    """Return a Databricks SDK config, importing the SDK lazily."""
    try:
        from databricks.sdk.core import Config
    except ImportError as exc:  # pragma: no cover - depends on the environment
        raise ImportError(
            "databricks-sdk is required to reflect Databricks tables; install "
            "etlalchemy[databricks]"
        ) from exc
    if profile is not None:
        return Config(profile=profile, **kwargs)
    return Config(**kwargs)


def _require_host(host: str | None) -> str:
    """Return a normalised host or raise the detection error."""
    if not host:
        raise ValueError(DETECTION_MESSAGE)
    return _normalise_host(host)


def _require_token(config: object) -> str:
    """Return the token of an SDK config or raise the detection error.

    ``databricks auth login`` profiles keep no static token: the SDK auth
    strategy exchanges the stored credentials for a bearer token instead, which
    is why a config without ``token`` is still usable.
    """
    token = _optional_token(config)
    if token:
        return token
    token = _authenticated_token(config)
    if token:
        return token
    raise ValueError(DETECTION_MESSAGE)


def _optional_token(config: object) -> str | None:
    """Return the static token of an SDK config, if it has one."""
    token = getattr(config, "token", None)
    if isinstance(token, str) and token:
        return token
    return None


def _authenticated_token(config: object) -> str | None:
    """Return the bearer token the config's auth strategy produces, if any."""
    authenticate = getattr(config, "authenticate", None)
    if not callable(authenticate):
        return None
    headers = authenticate()
    if not isinstance(headers, Mapping):
        return None
    authorization = headers.get("Authorization")
    if not isinstance(authorization, str):
        return None
    scheme, _, value = authorization.partition(" ")
    if scheme.lower() != "bearer" or not value:
        return None
    return value


def _normalise_host(host: str) -> str:
    """Strip the scheme, path and trailing slash from a host."""
    normalised = host.strip()
    for prefix in ("https://", "http://", "databricks://"):
        if normalised.startswith(prefix):
            normalised = normalised[len(prefix) :]
    normalised = normalised.split("/", 1)[0]
    return normalised.rstrip("/")


def _path_suffix(http_path: str | None) -> str:
    """Return the warehouse path without its leading and trailing slashes."""
    if not http_path:
        return ""
    return http_path.strip().strip("/")


def _http_path(http_path: str | None) -> str:
    """Return a warehouse path with its leading slash, or an empty string."""
    suffix = _path_suffix(http_path)
    return f"/{suffix}" if suffix else ""


def _path_from_env() -> str:
    """Return the warehouse path of the environment, if any."""
    return _http_path(os.environ.get("DATABRICKS_HTTP_PATH"))


def _runtime_url(host: str, http_path: str | None) -> str:
    """Build the URL of a connection that relies on ambient credentials."""
    base = f"databricks://{_normalise_host(host)}:{_PORT}"
    path = _http_path(http_path)
    return f"{base}?http_path={path}" if path else base


def _token_url(host: str, token: str, http_path: str | None) -> str:
    """Build a token URL; never log the result."""
    base = f"databricks://token:{token}@{_normalise_host(host)}:{_PORT}"
    path = _http_path(http_path)
    return f"{base}?http_path={path}" if path else base


def _default_config_path() -> Path:
    """Return the path of the Databricks CLI configuration file."""
    return Path.home() / ".databrickscfg"


def has_default_profile() -> bool:
    """Return whether ``~/.databrickscfg`` has a ``DEFAULT`` section."""
    path = _default_config_path()
    if not path.is_file():
        return False
    return any(line.strip() == "[DEFAULT]" for line in path.read_text().splitlines())


__all__ = ["DETECTION_MESSAGE", "databricks_connection"]
