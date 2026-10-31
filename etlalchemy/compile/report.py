"""Structured diagnostics produced while compiling a query.

Every diagnostic is a :class:`CompileEvent` identified by a stable ``code``,
tagged with a ``severity`` and the compile ``phase`` that produced it, and
carrying the entity, relationship, dimension, measure and join type it refers
to. A :class:`CompileReport` collects those events together with the join
decisions of the plan.
"""

from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from etlalchemy.compile.plan import FanoutRisk

#: An expression join cannot bind its literals when they are parameterized.
EXPRESSION_JOIN_UNBOUND = "EXPRESSION_JOIN_UNBOUND"
#: A LEFT join whose target side is filtered behaves like an INNER join.
LEFT_JOIN_FILTERED = "LEFT_JOIN_FILTERED"
#: A BOTH-direction relationship filtered on its target forces an INNER join.
BOTH_FILTER_FORCES_INNER = "BOTH_FILTER_FORCES_INNER"
#: A dimension was replaced by NULL because its entity cannot aggregate by it.
UNREACHABLE_DIMENSION = "UNREACHABLE_DIMENSION"
#: A fanout risk that was downgraded to a warning.
FANOUT_RISK = "FANOUT_RISK"
#: A fanout risk that rejects the query.
FANOUT_REJECTED = "FANOUT_REJECTED"
#: A time grain was requested on a field that is not a Date or Timestamp.
INVALID_TIME_GRAIN = "INVALID_TIME_GRAIN"


@dataclasses.dataclass(frozen=True)
class CompileEvent:
    """One structured diagnostic produced while compiling a query.

    Attributes:
        code: Stable identifier, one of the event code constants of this
            module.
        severity: ``"info"``, ``"warning"`` or ``"error"``.
        message: Human-readable description of the diagnostic.
        phase: Compile phase that produced the event, one of ``"resolve"``,
            ``"routes"``, ``"fanout"``, ``"plan"`` or ``"build"``.
        entity: Entity alias the event refers to, if any.
        relationship: Relationship name the event refers to, if any.
        dimension: Dimension output alias the event refers to, if any.
        measure: Measure name the event refers to, if any.
        join_type: Join type the event refers to, if any.
        payload: Object behind the event, such as a ``FanoutRisk``, if any.
    """

    code: str
    severity: str
    message: str
    phase: str
    entity: str | None = None
    relationship: str | None = None
    dimension: str | None = None
    measure: str | None = None
    join_type: str | None = None
    payload: object | None = None

    def __str__(self) -> str:
        """Return the human-readable message."""
        return self.message


@dataclasses.dataclass(frozen=True)
class JoinDecision:
    """One join the planner chose, and why.

    Attributes:
        relationship: Name of the relationship the join walks.
        join_type: Join type the planner picked, ``"LEFT"`` or ``"INNER"``.
        reason: Why that type was picked: ``"both_filter"`` for a BOTH
            direction, ``"many_to_many"`` for a multiplying edge,
            ``"one_to_many_single"`` for a ONE_TO_MANY edge in the SINGLE
            direction, and ``"one_to_one"`` otherwise.
        reversed: Whether the join walks the relationship from its target to
            its source.
    """

    relationship: str
    join_type: str
    reason: str
    reversed: bool = False


@dataclasses.dataclass
class CompileReport:
    """Structured diagnostics collected while compiling a query.

    Attributes:
        events: Every diagnostic the compilation produced, in order.
        join_decisions: One decision per join of the compiled plan.
        cte_count: Number of pre-aggregation CTEs the plan produced.

    Filter the diagnostics with :meth:`with_code` or :meth:`with_severity`.
    The ``warnings``, ``errors``, ``fanout_risks``, ``join_types`` and
    ``unreachable_dimension_warnings`` properties are compatibility views
    derived from ``events`` and ``join_decisions``.
    """

    events: list[CompileEvent] = dataclasses.field(default_factory=list)
    join_decisions: tuple[JoinDecision, ...] = ()
    cte_count: int = 0

    def add(self, event: CompileEvent) -> None:
        """Append one diagnostic event to the report."""
        self.events.append(event)

    def with_code(self, code: str) -> tuple[CompileEvent, ...]:
        """Return the events carrying ``code``."""
        return tuple(event for event in self.events if event.code == code)

    def with_severity(self, severity: str) -> tuple[CompileEvent, ...]:
        """Return the events carrying ``severity``."""
        return tuple(event for event in self.events if event.severity == severity)

    @property
    def warnings(self) -> tuple[CompileEvent, ...]:
        """Return the events of severity ``"warning"``."""
        return self.with_severity("warning")

    @property
    def errors(self) -> tuple[CompileEvent, ...]:
        """Return the events of severity ``"error"``."""
        return self.with_severity("error")

    @property
    def fanout_risks(self) -> tuple[FanoutRisk, ...]:
        """Return the fanout risks carried by the fanout events."""
        return tuple(
            cast("FanoutRisk", event.payload)
            for event in self.events
            if event.code in (FANOUT_RISK, FANOUT_REJECTED)
            and event.payload is not None
        )

    @property
    def join_types(self) -> tuple[tuple[str, str], ...]:
        """Return the ``(relationship name, join type)`` pairs of the plan."""
        return tuple(
            (decision.relationship, decision.join_type)
            for decision in self.join_decisions
        )

    @property
    def unreachable_dimension_warnings(self) -> tuple[str, ...]:
        """Return the messages of the unreachable-dimension events."""
        return tuple(
            event.message
            for event in self.events
            if event.code == UNREACHABLE_DIMENSION
        )


__all__ = [
    "BOTH_FILTER_FORCES_INNER",
    "EXPRESSION_JOIN_UNBOUND",
    "FANOUT_REJECTED",
    "FANOUT_RISK",
    "INVALID_TIME_GRAIN",
    "LEFT_JOIN_FILTERED",
    "UNREACHABLE_DIMENSION",
    "CompileEvent",
    "CompileReport",
    "JoinDecision",
]
