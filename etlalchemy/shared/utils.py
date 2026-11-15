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


def dump(data: Any) -> str:
    """Serialises read model data as JSON text."""
    return json.dumps(data, default=str, ensure_ascii=False)
