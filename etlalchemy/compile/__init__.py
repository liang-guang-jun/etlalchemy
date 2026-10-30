"""Semantic query compilation into dialect SQL and parameters.

``compile_query(query, model, dialect)`` resolves the query against a model,
picks the relationships the query traverses, plans its joins, builds a sqlglot
AST and renders it for the requested dialect.

First-version boundaries:

* a query must project at least one dimension or measure;
* a single fact entity compiles to one plain SELECT and emits no CTE;
* several fact entities compile to one pre-aggregation CTE per entity plus a
  merge query that ``FULL OUTER JOIN``s the CTEs on the full dimension set and
  ``COALESCE``s the dimension values;
* a fact entity that cannot reach a dimension is rejected by default
  (``unreachable_dimensions="error"``); with ``"null"`` the dimension is
  projected as NULL inside that CTE and reported in the compile report;
* only ``sum``, ``count``, ``avg``, ``min`` and ``max`` aggregations exist;
* predicates are limited to ``Comparison`` and ``Logical`` nodes; filters are
  pushed into the CTE that owns the referenced entities, an ``AND`` may span
  facts, but an ``OR`` spanning facts is rejected;
* every join is a ``LEFT`` or ``INNER`` join, never a semi-join yet;
* every literal becomes a bound parameter when ``bind_literals`` is set and is
  inlined into the SQL text otherwise;
* ORDER BY NULL placement follows ``nulls_first``: ``True`` renders
  ``NULLS FIRST``, ``False`` renders ``NULLS LAST`` and ``None`` renders no
  NULLS clause, leaving the placement to the target database.
"""

from etlalchemy.compile.compiler import compile_query

__all__ = ["compile_query"]
