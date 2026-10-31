"""Semantic query compilation into dialect SQL, parameters and a report.

``compile_query(query, model, dialect)`` resolves the query against a model,
picks the relationships the query traverses, plans its joins, builds a sqlglot
AST and renders it for the requested dialect. It returns a
:class:`~etlalchemy.compile.result.CompiledQuery`; read the statement through
``compiled.sql``, the parameters through ``compiled.params`` and the
diagnostics through ``compiled.report``.

Compile options:

* the default dialect is ``"databricks"``;
* literals are inlined into the SQL by default (``inline_literals=True``) and
  ``params`` is empty; ``inline_literals=False`` turns every literal into a
  placeholder and collects its value in ``params``;
* ``nulls_first`` defaults to ``None``, which renders no NULLS clause at all
  and leaves the placement to the target database.

First-version boundaries:

* a query must project at least one dimension or measure;
* a single fact entity compiles to one plain SELECT and emits no CTE;
* several fact entities compile to one pre-aggregation CTE per entity plus a
  merge query that ``FULL OUTER JOIN``s the CTEs on the full dimension set and
  ``COALESCE``s the dimension values;
* a fact entity that cannot reach a dimension is rejected by default
  (``unreachable_dimensions="error"``); with ``"null"`` the dimension is
  projected as NULL inside that CTE and reported in the compile report;
* only ``sum``, ``count``, ``count_distinct``, ``avg``, ``min`` and ``max``
  aggregations exist;
* a measure that a join can duplicate (fanout) is rejected for ``sum``,
  ``count`` and ``avg``, only reported as a warning for ``min``, ``max`` and
  ``count_distinct``, and always rejected for a MANY_TO_MANY edge;
* ``count`` without ``field`` or ``fields`` renders ``COUNT(*)`` and requires
  the measure to set ``entity``; ``count`` with ``field`` renders
  ``COUNT(field)`` and skips NULL values;
* ``count_distinct`` accepts a single ``field`` or a ``fields`` tuple whose
  columns belong to the measure entity; it is rejected when its fields span
  more than one entity, and together with ``count`` it is rejected when the
  query spans several fact entities, because the value cannot be merged across
  CTEs yet;
* the return value always carries the ``CompileReport`` with the fanout
  warnings and the join types of the plan;
* filters are parsed from a SQL-like DSL into ``Comparison``, ``Logical``,
  ``Not``, ``In``, ``Between``, ``IsNull``, ``Like`` and ``FieldComparison``
  nodes; filters are pushed into the CTE that owns the referenced entities, an
  ``AND`` may span facts, but an ``OR`` or a field-to-field comparison spanning
  facts is rejected;
* every join is a ``LEFT`` or ``INNER`` join, never a semi-join yet:
  ONE_TO_MANY relationships join with LEFT in the SINGLE filter direction, so a
  fact row without a matching dimension row is kept with NULL dimension values.
  BOTH and MANY_TO_MANY join with INNER, and ONE_TO_ONE joins with LEFT. A LEFT
  join whose target side is filtered still behaves like an INNER join, which the
  compile report records as a warning;
* every literal is inlined into the SQL text by default and becomes a bound
  parameter when ``inline_literals`` is False;
* ORDER BY NULL placement follows ``nulls_first``: ``True`` renders
  ``NULLS FIRST``, ``False`` renders ``NULLS LAST`` and ``None`` renders no
  NULLS clause, leaving the placement to the target database.
"""

from etlalchemy.compile.compiler import compile_query
from etlalchemy.compile.result import CompiledQuery

__all__ = ["CompiledQuery", "compile_query"]
