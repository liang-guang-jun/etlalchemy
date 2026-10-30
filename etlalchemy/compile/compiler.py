"""Compile expression queries into SQL text and parameters.

The query tree is complete enough to describe a query, but SQL generation has
not been implemented yet; the compiler raises ``NotImplementedError`` so
callers fail loudly instead of receiving invalid SQL.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from etlalchemy.core.expression import Query

if TYPE_CHECKING:
    from etlalchemy.core.model import SemanticModel


def compile_query(
    query: Query,
    model: SemanticModel,
    dialect: str = "postgres",
) -> tuple[str, list[object]]:
    """Return the SQL text and parameters for a query.

    Args:
        query: Query to compile.
        model: Model used to resolve the entity and measure references of the
            query.
        dialect: Target SQL dialect name.

    Raises:
        NotImplementedError: SQL generation is not implemented yet.
    """
    raise NotImplementedError(
        f"SQL compilation for dialect {dialect!r} is not implemented yet"
    )
