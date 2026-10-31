"""Reflect tables of an external database into the semantic model.

Reflection reads table metadata from a database, turns it into
:class:`~etlalchemy.reflect.table.ReflectedTable` objects, and — when asked —
into the semantic ``Rowset``/``SemanticEntity`` pair the rest of the package
compiles from.

The cache is pluggable: a
:class:`~etlalchemy.reflect.repositories.ReflectionRepository` stores reflected
tables, and every caller passes the storage explicitly.
"""

from __future__ import annotations

from etlalchemy.reflect.inspector import (
    LiveInspector,
    ReflectionSession,
    reflect_tables,
)
from etlalchemy.reflect.mapping import map_type, type_to_string
from etlalchemy.reflect.reflector import Reflector
from etlalchemy.reflect.repositories import (
    InMemoryReflectionRepository,
    JsonReflectionRepository,
    ReflectionRepository,
    SqlAlchemyReflectionRepository,
    YamlReflectionRepository,
)
from etlalchemy.reflect.source import ReflectSource
from etlalchemy.reflect.table import ReflectedColumn, ReflectedTable, as_entities

__all__ = [
    "InMemoryReflectionRepository",
    "JsonReflectionRepository",
    "LiveInspector",
    "ReflectedColumn",
    "ReflectedTable",
    "ReflectionRepository",
    "ReflectionSession",
    "Reflector",
    "ReflectSource",
    "SqlAlchemyReflectionRepository",
    "YamlReflectionRepository",
    "as_entities",
    "map_type",
    "reflect_tables",
    "type_to_string",
]
