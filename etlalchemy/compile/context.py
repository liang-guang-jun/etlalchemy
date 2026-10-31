"""Per-compilation state shared by the compile stages."""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping

from etlalchemy.compile.report import CompileReport
from etlalchemy.semantic.expression import Query, RouteKey
from etlalchemy.semantic.model import SemanticModel
from etlalchemy.semantic.rowset import SemanticEntity


@dataclasses.dataclass
class CompileContext:
    """State shared across one compilation.

    ``parameters`` collects the values bound to placeholders, ``entity_aliases``
    maps entity aliases to the SQL aliases used in the statement,
    ``entity_by_alias`` resolves the aliases written in a query, and
    ``measure_routes`` caches the effective routes of every measure the query
    touches. ``inline_literals`` decides whether literals are written into the
    SQL text (the default) or become placeholders collected in ``parameters``.
    ``nulls_first`` controls the NULL placement rendered in every ORDER BY term:
    ``True`` renders ``NULLS FIRST``, ``False`` renders ``NULLS LAST`` and
    ``None`` renders no NULLS clause so the target database default applies.
    ``report`` collects the structured diagnostics of the compilation.
    """

    model: SemanticModel
    query: Query
    dialect: str = "databricks"
    inline_literals: bool = True
    unreachable_dimensions: str = "error"
    nulls_first: bool | None = None
    parameters: dict[str, object] = dataclasses.field(default_factory=dict)
    entity_aliases: dict[str, str] = dataclasses.field(default_factory=dict)
    entity_by_alias: dict[str, SemanticEntity] = dataclasses.field(
        init=False, default_factory=dict
    )
    measure_routes: dict[str, Mapping[RouteKey, int]] = dataclasses.field(
        default_factory=dict
    )
    report: CompileReport = dataclasses.field(default_factory=CompileReport)

    def __post_init__(self) -> None:
        """Index the model entities by registry name and by entity alias."""
        for name, entity in self.model.registry.entities.items():
            self.entity_by_alias[entity.alias] = entity
            self.entity_by_alias[name] = entity

    def add_parameter(self, value: object) -> str:
        """Store a bound value and return its placeholder name."""
        name = f"param{len(self.parameters)}"
        self.parameters[name] = value
        return name

    def sql_alias(self, entity: SemanticEntity) -> str:
        """Return the SQL alias of an entity, assigning one on first use."""
        existing = self.entity_aliases.get(entity.alias)
        if existing is not None:
            return existing
        taken = set(self.entity_aliases.values())
        candidate = entity.alias
        counter = 2
        while candidate in taken:
            candidate = f"{entity.alias}_{counter}"
            counter += 1
        self.entity_aliases[entity.alias] = candidate
        return candidate
