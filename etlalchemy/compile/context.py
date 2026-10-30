"""Per-compilation state shared by the compile stages."""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping

from etlalchemy.semantic.expression import Query, RouteKey
from etlalchemy.semantic.model import SemanticModel
from etlalchemy.semantic.rowset import SemanticEntity


@dataclasses.dataclass
class CompileReport:
    """Diagnostics collected while planning a query.

    ``warnings`` records decisions that changed the shape of the statement,
    ``cte_count`` is the number of pre-aggregation CTEs the plan produced, and
    ``unreachable_dimension_warnings`` records dimensions that were replaced by
    NULL because an entity could not aggregate by them.
    """

    warnings: list[str] = dataclasses.field(default_factory=list)
    cte_count: int = 0
    unreachable_dimension_warnings: tuple[str, ...] = ()

    def add_warning(self, message: str) -> None:
        """Record one warning."""
        self.warnings.append(message)

    def add_unreachable_dimension(self, message: str) -> None:
        """Record one dimension that the plan replaced with NULL."""
        self.warnings.append(message)
        self.unreachable_dimension_warnings = (
            *self.unreachable_dimension_warnings,
            message,
        )


@dataclasses.dataclass
class CompileContext:
    """State shared across one compilation.

    ``parameters`` collects the values bound to placeholders, ``entity_aliases``
    maps entity aliases to the SQL aliases used in the statement,
    ``entity_by_alias`` resolves the aliases written in a query, and
    ``measure_routes`` caches the effective routes of every measure the query
    touches. ``bind_literals`` decides whether literals become placeholders or
    are inlined into the SQL text. ``nulls_first`` controls the NULL placement
    rendered in every ORDER BY term: ``True`` renders ``NULLS FIRST``, ``False``
    renders ``NULLS LAST`` and ``None`` renders no NULLS clause so the target
    database default applies.
    """

    model: SemanticModel
    query: Query
    dialect: str = "postgres"
    bind_literals: bool = False
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
