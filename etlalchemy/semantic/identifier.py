"""Qualified names of the relations a rowset reads from."""

from __future__ import annotations

import dataclasses


@dataclasses.dataclass(frozen=True)
class QualifiedName:
    """A relation name, optionally scoped by a schema and a catalog.

    The scope is rendered outermost first, so a name with a catalog is written
    ``catalog.schema.name``. A bare name renders as itself.
    """

    name: str
    schema: str | None = None
    catalog: str | None = None

    def to_sql(self) -> str:
        """Return the dotted name, outermost scope first.

        Returns:
            ``main.sales.orders`` with a catalog, ``sales.orders`` with a
            schema, and ``orders`` with neither.
        """
        parts = [part for part in (self.catalog, self.schema, self.name) if part]
        return ".".join(parts)

    def __str__(self) -> str:
        """Return the dotted name."""
        return self.to_sql()


__all__ = ["QualifiedName"]
