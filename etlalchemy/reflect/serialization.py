"""Serialise and deserialise reflected table metadata for caches.

The payload format is versioned: ``version`` 2 is the current format, and it
must be incremented whenever the shape of the payload changes. A cache whose
version does not match is ignored instead of being misread.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import cast

from etlalchemy.reflect.mapping import type_to_string
from etlalchemy.reflect.table import ReflectedColumn, ReflectedTable

#: Version of the payload written by :func:`tables_to_payload`.
PAYLOAD_VERSION = 3


def table_to_dict(table: ReflectedTable) -> dict[str, object]:
    """Return the JSON-ready form of one reflected table."""
    return {
        "name": table.name,
        "catalog": table.catalog,
        "schema": table.schema,
        "primary_key": list(table.primary_key),
        "columns": [
            {
                "name": column.name,
                "type_string": type_to_string(column.sa_type),
                "nullable": column.nullable,
            }
            for column in table.columns
        ],
    }


def table_from_dict(raw: Mapping[str, object]) -> ReflectedTable:
    """Rebuild one table from :func:`table_to_dict` output.

    The column type is kept as the cached ``type_string``; the mapping layer
    understands strings as well as SQLAlchemy types.
    """
    columns = cast("Sequence[Mapping[str, object]]", raw.get("columns") or ())
    primary_key = cast("Sequence[object]", raw.get("primary_key") or ())
    return ReflectedTable(
        name=str(raw["name"]),
        catalog=_text(raw.get("catalog")),
        schema=_text(raw.get("schema")),
        columns=tuple(
            ReflectedColumn(
                name=str(column["name"]),
                sa_type=str(column["type_string"]),
                nullable=bool(column["nullable"]),
            )
            for column in columns
        ),
        primary_key=tuple(str(name) for name in primary_key),
    )


def _text(value: object) -> str | None:
    """Return a cached name, or ``None`` when the payload does not carry one."""
    return None if value is None else str(value)


def tables_to_payload(
    tables: Iterable[ReflectedTable],
    *,
    complete: bool,
) -> dict[str, object]:
    """Return the versioned payload of a set of tables."""
    return {
        "version": PAYLOAD_VERSION,
        "complete": complete,
        "tables": [table_to_dict(table) for table in tables],
    }


def tables_from_payload(
    payload: Mapping[str, object],
) -> tuple[ReflectedTable, ...] | None:
    """Return the tables of a payload, or None when the version differs."""
    if payload.get("version") != PAYLOAD_VERSION:
        return None
    tables = cast("Sequence[Mapping[str, object]]", payload.get("tables") or ())
    return tuple(table_from_dict(table) for table in tables)


def payload_complete(payload: Mapping[str, object]) -> bool:
    """Return whether a payload was written by a complete reflection."""
    return bool(payload.get("complete"))


__all__ = [
    "PAYLOAD_VERSION",
    "payload_complete",
    "table_from_dict",
    "table_to_dict",
    "tables_from_payload",
    "tables_to_payload",
]
