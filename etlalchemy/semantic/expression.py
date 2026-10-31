"""Expression nodes and query starters.

The nodes are pure value objects: they reference entities, fields and measures
by name and never hold registry instances. ``RouteKey`` is the alias pair used
by relationship routes; graph-level selection keeps using entity id pairs.

There are two ways to start a query:

* ``model.q`` (a :class:`~etlalchemy.semantic.model.SemanticModel` property) binds
  the query to that model, so ``query.compile()`` can resolve entities and
  measures.
* The module-level ``q`` starts an unbound query, e.g.
  ``q.group_by("orders.status").calculate("revenue").limit(10)``. Its result
  has ``model is None`` and must be bound to a model before it can be
  compiled; start from ``model.q`` instead, or pass the model to the compiler
  directly.

Both paths return a new immutable ``Query`` and never modify the query they
were called on.

Output aliases: a dimension is renamed with ``group_by(..., alias="...")`` and
a measure with ``calculate(..., alias="...")``. Without an explicit alias a
dimension is named ``"entity__name"`` and a measure keeps its name. Ordering
terms (``order_by``) match these output aliases.

Time grain: ``group_by(..., time_grain="month")`` buckets one Date or
Timestamp dimension into one of ``TIME_GRAINS`` (``"day"``, ``"week"``,
``"month"``, ``"quarter"`` or ``"year"``), and the compiler renders the
bucket with ``DATE_TRUNC``. Only the bare unit names are accepted; ``"date"``
and ``start_of_*`` aliases are rejected. The first day of a ``"week"`` is
decided by the target dialect, and a grain on a field that is not a Date or
Timestamp is rejected while resolving the query.

Filter DSL: ``filter`` takes SQL-like boolean expressions that
:mod:`etlalchemy.semantic.filter_parser` turns into the nodes below. Fields are
fully qualified as ``alias.field``; literals are single- or double-quoted
strings (doubled quotes escape), numbers, ``TRUE``, ``FALSE`` and ``NULL``;
keywords are case-insensitive and ``AND`` binds tighter than ``OR``. Supported
forms:

* comparisons ``field = value`` with ``=``, ``!=``, ``<>``, ``<``, ``<=``, ``>``
  and ``>=``, where the right side is a literal or another field;
* ``IN (...)`` and ``NOT IN (...)``;
* ``BETWEEN low AND high`` and ``NOT BETWEEN low AND high``;
* ``IS NULL`` and ``IS NOT NULL``;
* ``LIKE pattern`` and ``NOT LIKE pattern``;
* ``NOT expr`` and parentheses around any expression.

Function calls and arithmetic inside filters are not supported.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from etlalchemy.compile.result import CompiledQuery
    from etlalchemy.semantic.model import SemanticModel

#: Key of one relationship route: ``(source alias, target alias)``.
RouteKey = tuple[str, str]

#: Time buckets accepted by ``group_by(..., time_grain=...)``.
TIME_GRAINS = ("day", "week", "month", "quarter", "year")

__all__ = [
    "Between",
    "Comparison",
    "FieldComparison",
    "FieldRef",
    "In",
    "IsNull",
    "Like",
    "Literal",
    "Logical",
    "MeasureRef",
    "Not",
    "OrderBy",
    "Predicate",
    "Projection",
    "Query",
    "RouteKey",
    "TIME_GRAINS",
    "q",
]


@dataclass(frozen=True)
class FieldRef:
    """Reference to one field of one entity, by alias and field name.

    ``alias`` is the output column name of the referenced field. When it is
    ``None`` the compiler generates a default alias of ``"entity__name"``.
    ``time_grain`` truncates the field to one of :data:`TIME_GRAINS`; it only
    applies to Date and Timestamp fields, and ``None`` groups by the raw value.
    The first day of ``time_grain="week"`` is decided by the target dialect.
    """

    entity: str
    name: str
    alias: str | None = None
    time_grain: str | None = None


@dataclass(frozen=True)
class MeasureRef:
    """Reference to a registered measure, with an optional output alias."""

    name: str
    alias: str | None = None


@dataclass(frozen=True)
class Literal:
    """A literal value compared against a field inside a predicate."""

    value: object


@dataclass(frozen=True)
class Comparison:
    """A predicate comparing one field with a literal value."""

    field: FieldRef
    operator: str
    value: Literal


@dataclass(frozen=True)
class FieldComparison:
    """A predicate comparing two fields, for example ``a.x > b.y``."""

    left: FieldRef
    operator: str
    right: FieldRef


@dataclass(frozen=True)
class In:
    """A predicate testing one field against a list of literals."""

    field: FieldRef
    values: tuple[Literal, ...]
    negated: bool = False


@dataclass(frozen=True)
class Between:
    """A predicate testing one field against an inclusive literal range."""

    field: FieldRef
    low: Literal
    high: Literal
    negated: bool = False


@dataclass(frozen=True)
class IsNull:
    """A predicate testing whether one field is NULL."""

    field: FieldRef
    negated: bool = False


@dataclass(frozen=True)
class Like:
    """A predicate matching one field against a LIKE pattern."""

    field: FieldRef
    pattern: Literal
    negated: bool = False


@dataclass(frozen=True)
class Not:
    """The negation of one predicate."""

    operand: Predicate


@dataclass(frozen=True)
class Logical:
    """A boolean combination of predicates sharing one operator."""

    operator: str
    operands: tuple[Predicate, ...]


type Predicate = (
    Comparison | Logical | Not | In | Between | IsNull | Like | FieldComparison
)
type Projection = FieldRef | MeasureRef


@dataclass(frozen=True)
class OrderBy:
    """One ordering term over a dimension or measure reference."""

    ref: str
    descending: bool = False


def _parse_field(text: str) -> FieldRef:
    """Parse an ``alias.field`` reference into a FieldRef."""
    entity, separator, name = text.partition(".")
    entity, name = entity.strip(), name.strip()
    if not separator or not entity or not name:
        raise ValueError(f"Expected 'alias.field', got {text!r}")
    return FieldRef(entity=entity, name=name)


@dataclass(frozen=True)
class Query:
    """An immutable query over dimensions, measures, filters and routes.

    The chainable methods append to the current query and return a new
    ``Query`` built with :func:`dataclasses.replace`, so a query value can be
    reused and extended safely.

    A Python attribute cannot be both the data and the method of a query, so
    the ``order_by`` and ``limit`` chains store their data in ``order_terms``
    and ``row_limit``; the methods keep the names callers type.

    ``routes`` fixes, per ``(source alias, target alias)`` pair, which
    relationship priority the query traverses. It is merged with the default
    routes of a measure by ``effective_routes``; pairs named by neither fall
    back to the highest priority, so an empty mapping means "use the highest
    priority everywhere".

    ``model`` is the optional model the query was started from. It is
    excluded from equality and from any future serialization, so two queries
    with the same content compare equal even when they target different
    models. ``compile`` requires a bound model; queries started from the
    module-level ``q`` are unbound, those started from ``model.q`` are bound.

    Dimensions and measures are projected under output aliases: pass
    ``alias=...`` to :meth:`group_by` or :meth:`calculate`, or accept the
    defaults ``"entity__name"`` for dimensions and the measure name for
    measures. :meth:`order_by` resolves against those output aliases and takes
    the alias plus a ``descending`` flag instead of a ``"ref DESC"`` string.
    """

    dimensions: tuple[FieldRef, ...] = ()
    measures: tuple[MeasureRef, ...] = ()
    filters: tuple[Predicate, ...] = ()
    routes: Mapping[RouteKey, int] = field(default_factory=dict)
    order_terms: tuple[OrderBy, ...] = ()
    row_limit: int | None = None
    model: SemanticModel | None = field(default=None, compare=False, repr=False)

    def group_by(
        self,
        *refs: str,
        alias: str | None = None,
        time_grain: str | None = None,
    ) -> Query:
        """Append ``alias.field`` dimensions and return a new query.

        ``alias`` renames the single output column and ``time_grain`` buckets
        it, so each is only valid when exactly one reference is given. Measures
        take an output alias through ``calculate(..., alias=...)`` instead.

        Args:
            refs: One or more ``alias.field`` references.
            alias: Output column name for the dimension.
            time_grain: Truncate the dimension to one of :data:`TIME_GRAINS`
                (``"day"``, ``"week"``, ``"month"``, ``"quarter"`` or
                ``"year"``). It only applies to Date and Timestamp fields and
                to a single reference; ``None`` groups by the raw value. The
                first day of ``"week"`` is decided by the target dialect.

        Returns:
            A new query with the dimensions appended.

        Raises:
            ValueError: If ``alias`` or ``time_grain`` is combined with several
                references, or if ``time_grain`` is not one of
                :data:`TIME_GRAINS`.
        """
        parsed = tuple(_parse_field(ref) for ref in refs)
        if alias is not None:
            if len(parsed) != 1:
                raise ValueError("alias is only valid with a single dimension")
            parsed = (dataclasses.replace(parsed[0], alias=alias),)
        if time_grain is not None:
            if len(parsed) != 1:
                raise ValueError("time_grain is only valid with a single dimension")
            if time_grain not in TIME_GRAINS:
                expected = ", ".join(TIME_GRAINS)
                raise ValueError(
                    f"Unsupported time_grain {time_grain!r}; expected one of {expected}"
                )
            parsed = (dataclasses.replace(parsed[0], time_grain=time_grain),)
        return dataclasses.replace(self, dimensions=(*self.dimensions, *parsed))

    def calculate(self, measure: str, alias: str | None = None) -> Query:
        """Append a measure, optionally under an output alias, as a new query."""
        return dataclasses.replace(
            self,
            measures=(*self.measures, MeasureRef(name=measure, alias=alias)),
        )

    def filter(self, *predicates: str) -> Query:
        """Append parsed filter expressions and return a new query.

        Each string goes through
        :func:`etlalchemy.semantic.filter_parser.parse_filter`, so it may nest
        parentheses, ``NOT``, ``AND``/``OR``, ``IN``, ``BETWEEN``, ``IS NULL``,
        ``LIKE``, field-to-field comparisons and literal lists. Fields must be
        fully qualified as ``alias.field``; a bare name is rejected with a hint.

        Args:
            *predicates: Filter expressions, one per string.

        Returns:
            A new query with the parsed predicates appended.

        Raises:
            ValueError: If an expression is empty or invalid; the message names
                the error position and quotes the surrounding text.
        """
        from etlalchemy.semantic.filter_parser import parse_filter

        parsed = tuple(parse_filter(text) for text in predicates)
        return dataclasses.replace(self, filters=(*self.filters, *parsed))

    def order_by(self, ref: str, descending: bool = False) -> Query:
        """Append one ordering term over an output alias.

        Args:
            ref: Output alias of a dimension or measure.
            descending: Sort descending when True, ascending when False.
        """
        return dataclasses.replace(
            self,
            order_terms=(
                *self.order_terms,
                OrderBy(ref=ref, descending=descending),
            ),
        )

    def route(self, source: str, target: str, priority: int) -> Query:
        """Fix the priority used between two entity aliases."""
        merged = {**self.routes, (source, target): priority}
        return dataclasses.replace(self, routes=merged)

    def limit(self, n: int) -> Query:
        """Cap the number of returned rows and return a new query."""
        if n < 0:
            raise ValueError(f"limit must be non-negative, got {n}")
        return dataclasses.replace(self, row_limit=n)

    def compile(
        self,
        dialect: str = "databricks",
        *,
        inline_literals: bool = True,
        pretty: bool = True,
        unreachable_dimensions: str = "error",
        nulls_first: bool | None = None,
    ) -> CompiledQuery:
        """Compile this query against its bound model into a compiled result.

        The compiler is imported lazily so the core layer does not pull in the
        SQL backend at import time.

        Args:
            dialect: Target SQL dialect name; defaults to ``"databricks"``.
            inline_literals: When True (default), literal values are written
                into the SQL text and ``params`` is empty. When False, every
                literal becomes a placeholder and its value is collected in
                ``params``. Inlining is convenient for debugging and for values
                that come from trusted code, but it must not be used with
                untrusted input: it can leak sensitive values into SQL logs and
                it defeats statement caching. Prefer ``inline_literals=False``
                for anything user-supplied.
            pretty: When True, format the SQL with line breaks and indentation.
            unreachable_dimensions: ``"error"`` (default) rejects a measure
                entity that cannot aggregate by one of the query dimensions,
                naming the entity and the dimension. ``"null"`` projects NULL
                for that dimension inside its CTE, coalesces it in the merge
                query and records a warning in the compile report.
            nulls_first: Where NULL values sort in every ORDER BY term. ``True``
                renders ``NULLS FIRST``, ``False`` renders ``NULLS LAST``, and
                ``None`` (default) renders no NULLS clause, leaving the
                placement to the target database. Passing ``True`` or ``False``
                keeps NULL placement identical across dialects; with ``None``
                the dialects disagree, for example ``ASC`` sorts NULLs last on
                Postgres but first on Databricks. The placement is a compile
                option, not part of the query: ``order_by`` keeps taking only a
                reference and a ``descending`` flag.

        Returns:
            A :class:`~etlalchemy.compile.result.CompiledQuery` holding the
            SQL text, the parameters, the compile report, the dialect, the
            literal mode and the NULL placement used. Read them through
            ``.sql``, ``.params`` and ``.report``.

        Raises:
            ValueError: If the query is not bound to a model, if
                ``unreachable_dimensions`` is not ``"error"`` or ``"null"``,
                or if a measure can be duplicated by a fanout join.
        """
        if self.model is None:
            raise ValueError(
                "Query is not bound to a model; build it with model.q instead of "
                "the module-level q"
            )
        from etlalchemy.compile.compiler import compile_query

        return compile_query(
            self,
            self.model,
            dialect=dialect,
            inline_literals=inline_literals,
            pretty=pretty,
            unreachable_dimensions=unreachable_dimensions,
            nulls_first=nulls_first,
        )


def group_by(
    *refs: str,
    alias: str | None = None,
    time_grain: str | None = None,
) -> Query:
    """Start a query with the given dimension references."""
    return Query().group_by(*refs, alias=alias, time_grain=time_grain)


def calculate(measure: str, alias: str | None = None) -> Query:
    """Start a query with the given measure."""
    return Query().calculate(measure, alias)


def filter(*predicates: str) -> Query:
    """Start a query with the given predicates."""
    return Query().filter(*predicates)


def order_by(ref: str, descending: bool = False) -> Query:
    """Start a query with an ordering term."""
    return Query().order_by(ref, descending)


def route(source: str, target: str, priority: int) -> Query:
    """Start a query with a fixed route between two entity aliases."""
    return Query().route(source, target, priority)


def limit(n: int) -> Query:
    """Start a query with a row limit."""
    return Query().limit(n)


class _QueryStarters:
    """Module-level query starters."""

    group_by = staticmethod(group_by)
    calculate = staticmethod(calculate)
    filter = staticmethod(filter)
    order_by = staticmethod(order_by)
    route = staticmethod(route)
    limit = staticmethod(limit)


q = _QueryStarters()
