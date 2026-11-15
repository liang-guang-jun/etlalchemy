"""Shared option parsing for the ingestion source adapters."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Literal, cast

if TYPE_CHECKING:
    from etlalchemy.ingestion.aggregates.connection import SourceConnection

_TYPE_POLICIES: frozenset[str] = frozenset({"fail", "json", "skip"})


def type_policy(connection: SourceConnection) -> Literal["fail", "json", "skip"]:
    """Returns the supported type policy configured on a connection."""
    policy = connection.options.get("type_policy", "fail")
    if policy not in _TYPE_POLICIES:
        return "fail"
    return cast(Literal["fail", "json", "skip"], policy)


def bool_option(connection: SourceConnection, key: str, default: bool) -> bool:
    """Parses a boolean option, falling back to ``default``."""
    raw = connection.options.get(key)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def int_option(connection: SourceConnection, key: str, default: int) -> int:
    """Parses an integer option, falling back to ``default``."""
    raw = connection.options.get(key)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def json_option(connection: SourceConnection, key: str) -> dict[str, str]:
    """Parses a JSON object option, returning ``{}`` on any parse error."""
    raw = connection.options.get(key)
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if not isinstance(parsed, dict):
        return {}
    return {str(key): str(value) for key, value in parsed.items()}
