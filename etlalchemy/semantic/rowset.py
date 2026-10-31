"""Fields, rowsets, entities and field collections.

This module groups the concepts that describe "what the data looks like":
Field, Rowset, SemanticEntity and FieldCollection.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from uuid import UUID

from etlalchemy.semantic.identifier import QualifiedName
from etlalchemy.semantic.types import DataType


@dataclass(frozen=True)
class Field:
    """A column-level member of a Rowset."""

    name: str
    data_type: DataType


class Materialization(StrEnum):
    """Physical form of a Rowset."""

    TABLE = "table"
    QUERY = "query"
    VIEW = "view"
    CTE = "cte"


@dataclass
class Rowset:
    """Semantic wrapper for a table, query, view or CTE, holding its Fields.

    ``name`` is a :class:`~etlalchemy.semantic.identifier.QualifiedName` so a
    reflected table keeps the schema and the catalog it was read from. A plain
    string is still accepted and wrapped in a bare name.
    """

    name: QualifiedName | str
    kind: Materialization
    fields: dict[str, Field] = field(default_factory=dict)
    primary_key: list[str] | None = None

    def __post_init__(self) -> None:
        """Wrap a bare string in a ``QualifiedName``."""
        if isinstance(self.name, str):
            self.name = QualifiedName(self.name)

    @property
    def sql_name(self) -> str:
        """Return the dotted name used when the Rowset is rendered as SQL."""
        if isinstance(self.name, QualifiedName):
            return self.name.to_sql()
        return self.name


@dataclass(frozen=True)
class SemanticEntity:
    """Alias wrapper for a Rowset; alias is the source of SQL aliases."""

    id: UUID
    alias: str
    relation: Rowset


@dataclass(frozen=True)
class FieldCollection:
    """Ordered fields of one SemanticEntity, used for composite-key joins."""

    entity: SemanticEntity
    fields: tuple[Field, ...]

    def __post_init__(self) -> None:
        """Validate that fields are unique and belong to the entity's Rowset."""
        names = {f.name for f in self.fields}
        if len(names) != len(self.fields):
            raise ValueError("Duplicate field names in FieldCollection")
        missing = names - set(self.entity.relation.fields)
        if missing:
            raise ValueError(
                f"Fields not found in Rowset {self.entity.relation.name}: {missing}"
            )
