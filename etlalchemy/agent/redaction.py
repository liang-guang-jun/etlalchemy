"""Redaction and previews of tool arguments and results.

The browser shows what a tool was called with and what it returned, while the
model sees the payload in full. A credential must never reach the browser, so
every argument mapping is redacted before it is previewed, and both previews are
bounded by the run limits: they travel in the stream and are stored with the
message, so an unbounded preview would grow the event store.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any

REDACTED = "***"
"""Placeholder that replaces a sensitive argument value."""

TRUNCATION_MARKER = "…(truncated)"
"""Suffix appended to an over-long preview."""

DEFAULT_REDACT_KEYS: tuple[str, ...] = (
    "api_key",
    "api_token",
    "authorization",
    "credential",
    "credential_ref",
    "password",
    "private_key",
    "secret",
    "token",
)
"""Argument names that are masked by default, matched case-insensitively."""

_SEPARATORS = re.compile(r"[^a-z0-9]+")

_CAMEL_CASE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")


def _normalise(key: str) -> str:
    """Returns the comparable form of an argument name."""
    separated = _CAMEL_CASE.sub("_", key.strip())
    return _SEPARATORS.sub("_", separated.lower()).strip("_")


def redact_arguments(arguments: Mapping[str, Any], keys: frozenset[str]) -> dict[str, Any]:
    """Returns a copy of the arguments with sensitive values masked.

    Matching is case-insensitive, compares the normalised name (so ``apiKey``
    matches ``api_key``) and compares the last segment of a dotted or nested
    path, so ``options.token`` and ``{"options": {"token": …}}`` are masked too.

    Args:
        arguments: Parsed tool arguments.
        keys: Argument names whose value must never be shown.

    Returns:
        A JSON-safe copy of the arguments; the input is not mutated.
    """
    redacted: dict[str, Any] = _redact(arguments, frozenset(_normalise(key) for key in keys))
    return redacted


def _is_sensitive(key: str, keys: frozenset[str]) -> bool:
    """Returns whether one argument name must be masked."""
    normalised = _normalise(key)
    if normalised in keys:
        return True
    tail = normalised.rsplit("_", 1)[-1]
    return tail != normalised and tail in keys


def _redact(value: Any, keys: frozenset[str]) -> Any:
    """Walks a JSON-safe value and masks every sensitive key it meets."""
    if isinstance(value, Mapping):
        return {
            str(key): REDACTED if _is_sensitive(str(key), keys) else _redact(item, keys)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_redact(item, keys) for item in value]
    return value


def preview_text(text: str, limit: int) -> str:
    """Truncates text to ``limit`` characters, marking the cut.

    Args:
        text: Text to shorten.
        limit: Maximum length, or ``0`` for no limit.

    Returns:
        The text, or its prefix followed by :data:`TRUNCATION_MARKER`.
    """
    if limit <= 0 or len(text) <= limit:
        return text
    return text[: max(0, limit - len(TRUNCATION_MARKER))] + TRUNCATION_MARKER


def preview_json(value: Any, limit: int) -> str:
    """Renders a JSON-safe value as compact text, truncated to ``limit``.

    Args:
        value: Value to render, usually an already-redacted argument mapping.
        limit: Maximum length, or ``0`` for no limit.

    Returns:
        The JSON text the browser shows in the tool drawer.
    """
    text = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return preview_text(text, limit)
