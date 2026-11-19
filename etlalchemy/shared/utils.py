"""Small helpers shared by every bounded context and the delivery layer."""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID


def uuid_or_none(value: str) -> UUID | None:
    """Returns the value as a UUID, or None when it is malformed."""
    try:
        return UUID(value)
    except ValueError:
        return None


def as_uuid(value: UUID | str) -> UUID:
    """Returns the given value as a :class:`UUID`.

    Raises:
        ValueError: If the value is a string that is not a UUID.
    """
    return value if isinstance(value, UUID) else UUID(value)


def dump(data: Any) -> str:
    """Serialises read model data as JSON text."""
    return json.dumps(data, default=str, ensure_ascii=False)


DEFAULT_TARGET_TYPES: frozenset[str] = frozenset(
    {
        "catalog",
        "schema",
        "table",
        "field",
        "semantic_model",
        "semantic_entity",
        "relationship",
        "domain",
        "term",
        "ingestion_connection",
        "import_run",
        "tenant",
        "user",
        "group",
    }
)
"""Target types a comment thread accepts out of the box.

The comment context owns the registry, but the setting that restricts it is read
by the assembly layer, which must not import a context, so the vocabulary lives
here. Every entry is addressable by a UUID.
"""

PROFILE_KINDS: frozenset[str] = frozenset({"databricks_ai_gateway"})
"""LLM provider kinds that can authenticate through a Databricks CLI profile.

The LLM provider context validates against this set while the assembly layer
reads it to validate settings, so it lives where both may import it.
"""
