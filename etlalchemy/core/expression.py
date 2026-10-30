"""Expression nodes and query starters.

The nodes are pure value objects: they reference entities, fields and measures
by name and never hold registry instances. ``RouteKey`` is the alias pair used
by relationship routes; graph-level selection keeps using entity id pairs.

There are two ways to start a query:

* ``model.q`` (a :class:`~etlalchemy.core.model.SemanticModel` property) binds
  the query to that model, so ``query.compile()`` can resolve entities and
  measures.
* The module-level ``q`` starts an unbound query, e.g.
  ``q.group_by("orders.status").calculate("revenue").limit(10)``. Its result
  has ``model is None`` and must be bound to a model before it can be
  compiled; start from ``model.q`` instead, or pass the model to the compiler
  directly.

Both paths return a new immutable ``Query`` and never modify the query they
were called on.
"""

from __future__ import annotations

import dataclasses
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from etlalchemy.core.model import SemanticModel

#: Key of one relationship route: ``(source alias, target alias)``.
RouteKey = tuple[str, str]

__all__ = [
    "Comparison",
    "FieldRef",
    "Literal",
    "Logical",
    "MeasureRef",
    "OrderBy",
    "Predicate",
    "Projection",
    "Query",
    "RouteKey",
    "q",
]


@dataclass(frozen=True)
class FieldRef:
    """Reference to one field of one entity, by alias and field name."""

    entity: str
    name: str


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
class Logical:
    """A boolean combination of predicates sharing one operator."""

    operator: str
    operands: tuple[Comparison | Logical, ...]


type Predicate = Comparison | Logical
type Projection = FieldRef | MeasureRef


@dataclass(frozen=True)
class OrderBy:
    """One ordering term over a dimension or measure reference."""

    ref: str
    descending: bool = False


_COMPARISON = re.compile(
    r"^(?P<field>[A-Za-z_]\w*(?:\.\w+)*)\s*"
    r"(?P<operator><=|>=|<>|!=|=|<|>)\s*"
    r"(?P<value>.+)$"
)
_LOGICAL = re.compile(r"\s+(?P<operator>AND|OR)\s+", re.IGNORECASE)
_ORDER_TERM = re.compile(
    r"^(?P<ref>.+?)(?:\s+(?P<direction>ASC|DESC))?$", re.IGNORECASE
)


def _parse_field(text: str) -> FieldRef:
    """Parse an ``alias.field`` reference into a FieldRef."""
    entity, separator, name = text.partition(".")
    entity, name = entity.strip(), name.strip()
    if not separator or not entity or not name:
        raise ValueError(f"Expected 'alias.field', got {text!r}")
    return FieldRef(entity=entity, name=name)


def _parse_literal(text: str) -> Literal:
    """Parse a quoted string, number, boolean or NULL literal."""
    raw = text.strip()
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in {"'", '"'}:
        quote = raw[0]
        return Literal(raw[1:-1].replace(quote * 2, quote))
    upper = raw.upper()
    if upper in {"TRUE", "FALSE"}:
        return Literal(upper == "TRUE")
    if upper == "NULL":
        return Literal(None)
    try:
        return Literal(int(raw))
    except ValueError:
        pass
    try:
        return Literal(float(raw))
    except ValueError:
        return Literal(raw)


def _parse_comparison(text: str) -> Comparison:
    """Parse a single ``alias.field <operator> literal`` predicate."""
    match = _COMPARISON.match(text.strip())
    if match is None:
        raise ValueError(f"Unsupported predicate: {text!r}")
    return Comparison(
        field=_parse_field(match.group("field")),
        operator=match.group("operator"),
        value=_parse_literal(match.group("value")),
    )


def _parse_predicate(text: str) -> Predicate:
    """Parse a predicate, allowing one level of AND or OR composition."""
    parts = _LOGICAL.split(text.strip())
    if len(parts) == 1:
        return _parse_comparison(text)
    operands = tuple(_parse_comparison(item) for item in parts[0::2])
    operators = {item.upper() for item in parts[1::2]}
    if len(operators) != 1:
        raise ValueError(f"Mixed logical operators in {text!r}")
    return Logical(operator=operators.pop(), operands=operands)


def _parse_order_term(text: str) -> OrderBy:
    """Parse ``ref [ASC|DESC]`` into an ordering term."""
    match = _ORDER_TERM.match(text.strip())
    if match is None or not match.group("ref").strip():
        raise ValueError(f"Unsupported ordering term: {text!r}")
    direction = (match.group("direction") or "ASC").upper()
    return OrderBy(ref=match.group("ref").strip(), descending=direction == "DESC")


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
    """

    dimensions: tuple[FieldRef, ...] = ()
    measures: tuple[MeasureRef, ...] = ()
    filters: tuple[Predicate, ...] = ()
    routes: Mapping[RouteKey, int] = field(default_factory=dict)
    order_terms: tuple[OrderBy, ...] = ()
    row_limit: int | None = None
    model: SemanticModel | None = field(default=None, compare=False, repr=False)

    def group_by(self, *refs: str) -> Query:
        """Append ``alias.field`` dimensions and return a new query."""
        parsed = tuple(_parse_field(ref) for ref in refs)
        return dataclasses.replace(self, dimensions=(*self.dimensions, *parsed))

    def calculate(self, measure: str, alias: str | None = None) -> Query:
        """Append a measure, optionally under an output alias, as a new query."""
        return dataclasses.replace(
            self,
            measures=(*self.measures, MeasureRef(name=measure, alias=alias)),
        )

    def filter(self, *predicates: str) -> Query:
        """Append parsed predicates and return a new query."""
        parsed = tuple(_parse_predicate(text) for text in predicates)
        return dataclasses.replace(self, filters=(*self.filters, *parsed))

    def order_by(self, ref: str) -> Query:
        """Append an ordering term parsed from ``ref [ASC|DESC]``."""
        return dataclasses.replace(
            self, order_terms=(*self.order_terms, _parse_order_term(ref))
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

    def compile(self, dialect: str = "postgres") -> tuple[str, list[object]]:
        """Compile this query against its bound model into SQL and parameters.

        The compiler is imported lazily so the core layer does not pull in the
        SQL backend at import time.

        Args:
            dialect: Target SQL dialect name.

        Returns:
            The SQL text and its bound parameters.

        Raises:
            ValueError: If the query is not bound to a model.
        """
        if self.model is None:
            raise ValueError(
                "Query is not bound to a model; build it from model.q or "
                "attach a model before compiling"
            )
        from etlalchemy.compile.compiler import compile_query

        return compile_query(self, self.model, dialect=dialect)


def group_by(*refs: str) -> Query:
    """Start a query with the given dimension references."""
    return Query().group_by(*refs)


def calculate(measure: str, alias: str | None = None) -> Query:
    """Start a query with the given measure."""
    return Query().calculate(measure, alias)


def filter(*predicates: str) -> Query:
    """Start a query with the given predicates."""
    return Query().filter(*predicates)


def order_by(ref: str) -> Query:
    """Start a query with the given ordering term."""
    return Query().order_by(ref)


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
