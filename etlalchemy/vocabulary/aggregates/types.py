"""Value objects shared by the vocabulary aggregates."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from etlalchemy.vocabulary.aggregates.errors import InvalidColorError


class TermStatus(StrEnum):
    """Lifecycle status of a glossary term."""

    DRAFT = "draft"
    """Term is editable and not yet reviewed."""

    APPROVED = "approved"
    """Term content is final and must be reopened before it changes."""

    DEPRECATED = "deprecated"
    """Term is retired and must be reactivated before it changes."""


TARGET_KINDS: frozenset[str] = frozenset({"catalog", "schema", "table", "field"})
"""Kinds of catalog objects a term can be linked to."""


DEFAULT_TERM_COLOR = ""
"""Colour of a term that has none; the read model stores this instead of ``NULL``."""

_COLOR_PATTERN = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")
"""Accepted term colours: a ``#`` followed by three or six hex digits."""


def normalise_color(value: str | None) -> str:
    """Returns ``value`` as a lowercase ``#rrggbb`` colour or the empty string.

    ``None`` and an empty string both mean "no colour". The short ``#rgb`` form
    is expanded so the read model and the UI only ever see one representation.

    Raises:
        InvalidColorError: The value is neither blank nor a hex colour.
    """
    if value is None:
        return DEFAULT_TERM_COLOR
    candidate = value.strip().lower()
    if candidate == "":
        return DEFAULT_TERM_COLOR
    if not _COLOR_PATTERN.match(candidate):
        msg = f"colour must be empty or a hex value such as #f2c811, got {value!r}"
        raise InvalidColorError(msg)
    if len(candidate) == 4:
        return "#" + "".join(char * 2 for char in candidate[1:])
    return candidate


@dataclass(frozen=True, slots=True)
class TermLink:
    """A link from a term to one catalog object or one field of a table."""

    target_id: UUID
    """ID of the catalog, schema or table, or the owning table of a field."""
    target_kind: str
    """One of :data:`TARGET_KINDS`."""
    field_name: str = ""
    """Field name of a ``field`` link; empty for every other kind."""
