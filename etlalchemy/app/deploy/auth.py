"""Resolving Databricks CLI profile credentials for the deployment client.

The SDK stays an optional dependency: the profile store, the OAuth token
exchange and every credential type (PAT, OAuth, Azure CLI) are SDK concerns, so
the deployment only asks it for a host and an authentication header.
"""

from __future__ import annotations

import importlib
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from etlalchemy.app.deploy.errors import ProfileResolutionError

INSTALL_HINT = "install the 'databricks' extra: uv sync --extra databricks"
"""Message appended when the SDK is missing."""


@dataclass(frozen=True, slots=True)
class Credentials:
    """Workspace host and authentication headers of one profile."""

    host: str
    """Base URL of the workspace, without a trailing slash."""

    headers: Mapping[str, str]
    """Headers the SDK produced for the profile, including the bearer token."""


def resolve_credentials(profile: str) -> Credentials:
    """Resolves a Databricks CLI profile into a host and authentication headers.

    Args:
        profile: Profile name from ``--profile``; an empty string lets the SDK
            pick the default profile itself.

    Returns:
        The host and the headers every request has to carry.

    Raises:
        ProfileResolutionError: When the SDK is missing, the profile records no
            host, or the SDK produces no authentication header.
    """
    config_class = _config_class()
    try:
        config = config_class(profile=profile or None)
    except Exception as exc:  # the SDK raises its own hierarchy for a bad profile
        msg = f"cannot load the Databricks profile {profile or 'DEFAULT'}: {exc}"
        raise ProfileResolutionError(msg) from exc
    host = str(getattr(config, "host", "") or "").strip().rstrip("/")
    if not host:
        msg = (
            f"the Databricks profile {profile or 'DEFAULT'} records no workspace host; "
            "configure it with 'databricks configure --profile <name>'"
        )
        raise ProfileResolutionError(msg)
    headers = _authenticate(config, profile)
    return Credentials(host=host, headers=headers)


def _config_class() -> Any:
    """Imports the SDK configuration class lazily.

    Returns:
        The ``databricks.sdk.core.Config`` class.

    Raises:
        ProfileResolutionError: When the Databricks extra is not installed.
    """
    try:
        module = importlib.import_module("databricks.sdk.core")
    except ImportError as exc:
        msg = f"deploying to Databricks Apps needs databricks-sdk: {INSTALL_HINT}"
        raise ProfileResolutionError(msg) from exc
    return module.Config


def _authenticate(config: Any, profile: str) -> dict[str, str]:
    """Returns the headers the SDK computed for a profile.

    A profile may authenticate with a static PAT or an OAuth token exchange, so
    the headers are taken from ``authenticate()`` instead of ``config.token``.

    Args:
        config: Resolved SDK configuration.
        profile: Profile name, used in the error message only.

    Returns:
        The authentication headers.

    Raises:
        ProfileResolutionError: When the SDK produces no header at all.
    """
    try:
        headers = dict(config.authenticate() or {})
    except Exception as exc:  # expired token, unreachable metadata service, ...
        msg = f"the Databricks profile {profile or 'DEFAULT'} could not authenticate: {exc}"
        raise ProfileResolutionError(msg) from exc
    if not headers:
        msg = f"the Databricks profile {profile or 'DEFAULT'} produced no authentication header"
        raise ProfileResolutionError(msg)
    return headers
