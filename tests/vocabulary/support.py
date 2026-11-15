"""Fakes shared by the vocabulary context tests."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class FakeField:
    """Field row with the only attribute link validation reads."""

    name: str


class FakeCatalogView:
    """Catalog view that reports the objects a test declared as existing.

    ``VocabularyApplication`` only needs the four lookups used to validate term
    links, so the fake implements exactly those and nothing else.
    """

    def __init__(self) -> None:
        """Starts with an empty catalog tree."""
        self.catalogs: set[UUID] = set()
        self.schemas: set[UUID] = set()
        self.tables: set[UUID] = set()
        self.fields: dict[UUID, set[str]] = {}

    async def get_catalog(self, catalog_id: UUID) -> object | None:
        """Returns a placeholder when the catalog exists."""
        return object() if catalog_id in self.catalogs else None

    async def get_schema(self, schema_id: UUID) -> object | None:
        """Returns a placeholder when the schema exists."""
        return object() if schema_id in self.schemas else None

    async def get_table(self, table_id: UUID) -> object | None:
        """Returns a placeholder when the table exists."""
        return object() if table_id in self.tables else None

    async def list_fields(self, table_id: UUID) -> list[FakeField]:
        """Returns the fields declared for the table."""
        return [FakeField(name=name) for name in sorted(self.fields.get(table_id, set()))]
