"""The value a compiled query returns."""

from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from etlalchemy.compile.report import CompileReport


@dataclasses.dataclass(frozen=True)
class CompiledQuery:
    """The result of compiling a semantic query.

    Attributes:
        sql: Rendered SQL text.
        params: Bound parameters, empty when literals are inlined.
        report: Diagnostics collected during compilation.
        dialect: SQL dialect the statement was rendered for.
        inline_literals: Whether literals were inlined into the SQL.
        nulls_first: NULL placement used in ORDER BY terms, or None
            when no NULLS clause was rendered.
        identifier_case: Identifier casing applied to the rendered SQL.
        indent_width: Number of spaces per indentation level of the SQL.
    """

    sql: str
    params: list[object] | dict[str, object]
    report: CompileReport
    dialect: str
    inline_literals: bool
    nulls_first: bool | None
    identifier_case: str = "preserve"
    indent_width: int = 2


__all__ = ["CompiledQuery"]
