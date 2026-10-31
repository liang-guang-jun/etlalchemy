"""Reflected table and column value objects.

A reflected column keeps either the SQLAlchemy type instance read from a live
database or the type string stored in a cache. ``ReflectedTable`` turns itself
into the semantic ``Rowset``/``SemanticEntity`` pair the rest of the package
consumes.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Iterable, Mapping
from uuid import uuid4

import sqlalchemy as sa

from etlalchemy.reflect.mapping import map_type
from etlalchemy.semantic.identifier import QualifiedName
from etlalchemy.semantic.rowset import (
    Field,
    Materialization,
    Rowset,
    SemanticEntity,
)


@dataclasses.dataclass(frozen=True)
class ReflectedColumn:
    """One reflected column, before it becomes a semantic ``Field``.

    ``sa_type`` is a SQLAlchemy type instance on a live reflection and the
    cached type string when the table was read from a repository.
    """

    name: str
    sa_type: object
    nullable: bool


@dataclasses.dataclass(frozen=True)
class ReflectedTable:
    """One reflected table: where it lives, its columns and primary key.

    ``catalog`` and ``schema`` are where the table was reflected from, so a
    rowset made from it keeps the qualified name of the source table instead of
    losing it to a bare name.

    ``sqlalchemy_table`` is the live ``Table`` object when the table was
    reflected from a database. It lets :meth:`as_rowset` use the authoritative
    SQLAlchemy types instead of the reflected ones; cached tables leave it
    ``None`` and fall back to the stored type of each column.
    """

    name: str
    columns: tuple[ReflectedColumn, ...]
    primary_key: tuple[str, ...]
    catalog: str | None = None
    schema: str | None = None
    sqlalchemy_table: sa.Table | None = None

    @property
    def qualified_name(self) -> QualifiedName:
        """Return the name of the table as its source spells it."""
        return QualifiedName(self.name, schema=self.schema, catalog=self.catalog)

    def as_rowset(self) -> Rowset:
        """Return this table as a semantic ``Rowset`` under its source name.

        The rowset keeps the catalog and the schema the table was reflected
        from, so it is never renamed to say where it comes from. Only
        :meth:`as_entity` names it again, because an entity wraps the rowset in
        a container of its own.

        Returns:
            A table-backed rowset with one field per column.
        """
        fields = {
            column.name: Field(
                name=column.name,
                data_type=map_type(self._column_type(column)),
            )
            for column in self.columns
        }
        return Rowset(
            name=self.qualified_name,
            kind=Materialization.TABLE,
            fields=fields,
            primary_key=list(self.primary_key) or None,
        )

    def as_entity(self, alias: str | None = None) -> SemanticEntity:
        """Return a new entity over a new rowset of this table.

        Args:
            alias: Entity alias; the table name when ``None``. The alias is the
                name the entity gives the rowset it holds, the way a container
                labels its contents.

        Returns:
            A new entity with its own id and its own rowset.
        """
        return SemanticEntity(
            id=uuid4(),
            alias=alias or self.name,
            relation=self.as_rowset(),
        )

    def _column_type(self, column: ReflectedColumn) -> object:
        """Return the live SQLAlchemy type of a column when it is available."""
        if self.sqlalchemy_table is not None:
            reflected = self.sqlalchemy_table.c.get(column.name)
            if reflected is not None:
                return reflected.type
        return column.sa_type


def as_entities(
    tables: Iterable[ReflectedTable],
    aliases: Mapping[str, str] | None = None,
) -> tuple[SemanticEntity, ...]:
    """Return one entity per table, sorted by table name.

    Args:
        tables: Reflected tables to convert.
        aliases: Optional ``table name -> entity alias`` overrides.

    Returns:
        One entity per table; each has its own rowset and id.
    """
    overrides = aliases or {}
    return tuple(
        table.as_entity(alias=overrides.get(table.name))
        for table in sorted(tables, key=lambda item: item.name)
    )


__all__ = ["ReflectedColumn", "ReflectedTable", "as_entities"]
