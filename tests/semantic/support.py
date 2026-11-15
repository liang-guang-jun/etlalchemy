"""Fakes shared by the semantic context tests."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID, uuid4


@dataclass(frozen=True)
class FakeTable:
    """Table row with the only attributes the semantic application reads."""

    name: str


@dataclass(frozen=True)
class FakeField:
    """Field row with the only attributes the semantic application reads."""

    name: str


class FakeCatalogView:
    """Catalog view that reports the tables and fields a test declared.

    ``ModelApplication`` only needs the table lookup and the field listing used to
    validate entity tables and relationship references, so the fake implements
    exactly those and nothing else.
    """

    def __init__(self) -> None:
        """Starts with an empty catalog tree."""
        self.tables: dict[UUID, str] = {}
        self.fields: dict[UUID, set[str]] = {}

    def add_table(self, name: str, *field_names: str) -> UUID:
        """Declares a table with the given fields and returns its ID."""
        table_id = uuid4()
        self.tables[table_id] = name
        self.fields[table_id] = set(field_names)
        return table_id

    async def get_table(self, table_id: UUID) -> FakeTable | None:
        """Returns the table row when the table exists."""
        name = self.tables.get(table_id)
        return None if name is None else FakeTable(name=name)

    async def list_fields(self, table_id: UUID) -> list[FakeField]:
        """Returns the fields declared for the table."""
        return [FakeField(name=name) for name in sorted(self.fields.get(table_id, set()))]
