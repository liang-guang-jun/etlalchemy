"""Join conditions between two semantic entities.

``JoinCondition`` is the protocol every condition implements: it names the two
entities it connects and renders its ON clause for a pair of table aliases.
``EquiJoin`` compares the fields of two ``FieldCollection`` objects column by
column, which keeps the original relationship behaviour. ``ExpressionJoin``
renders an arbitrary SQL predicate that references the joined tables through
the ``{source}`` and ``{target}`` placeholders.

``EquiJoin`` names its ``FieldCollection`` fields ``source`` and ``target``,
while ``ExpressionJoin`` only needs the entity aliases and names them
``source_entity`` and ``target_entity``. Callers that do not know which kind
they hold use ``source_entity_alias()`` and ``target_entity_alias()``.

First-version limits of ``ExpressionJoin``: the expression cannot bind literal
parameters (the caller must express such values through a filter predicate),
it only supports ``filter_direction="SINGLE"``, and it rejects any placeholder
other than exactly ``{source}`` and ``{target}``. Format specifiers
(``{source:...}``), conversions (``{source!r}``), nested or doubled braces and
unbalanced braces are all rejected.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from etlalchemy.semantic.rowset import FieldCollection

#: Placeholders an expression join may use.
_ALLOWED_PLACEHOLDERS = frozenset({"{source}", "{target}"})

#: Error message used when the expression braces do not form placeholders.
_MALFORMED_PLACEHOLDER = (
    "Join expression has malformed placeholders; only {source} and {target} "
    "are supported"
)


def _placeholder_tokens(expression: str) -> set[str]:
    """Return the ``{...}`` tokens of an expression, rejecting stray braces.

    Raises:
        ValueError: If braces remain outside a complete ``{...}`` token, as in
            ``{source``, or if one token opens twice, as in ``{{source}}``.
    """
    tokens = set(re.findall(r"\{[^}]*\}", expression))
    for token in tokens:
        if token.count("{") > 1:
            raise ValueError(_MALFORMED_PLACEHOLDER)
    remainder = expression
    for token in tokens:
        remainder = remainder.replace(token, "")
    if "{" in remainder or "}" in remainder:
        raise ValueError(_MALFORMED_PLACEHOLDER)
    return tokens


@runtime_checkable
class JoinCondition(Protocol):
    """Protocol every join condition implements."""

    def source_entity_alias(self) -> str:
        """Return the alias of the source entity."""
        ...

    def target_entity_alias(self) -> str:
        """Return the alias of the target entity."""
        ...

    def referenced_entities(self) -> tuple[str, str]:
        """Return the pair of entity aliases this condition touches."""
        ...

    def to_sql(
        self,
        source_alias: str,
        target_alias: str,
        bind_literals: bool,
        add_parameter: Callable[[object], str],
    ) -> tuple[str, list[object]]:
        """Return the ON clause SQL and its bound parameters."""
        ...


@dataclass(frozen=True)
class EquiJoin:
    """Column-by-column equality join between two FieldCollections."""

    source: FieldCollection
    target: FieldCollection

    def __post_init__(self) -> None:
        """Validate that both sides have the same number of fields."""
        if len(self.source.fields) != len(self.target.fields):
            raise ValueError(
                f"Composite key length mismatch: "
                f"source={len(self.source.fields)} "
                f"target={len(self.target.fields)}"
            )

    def source_entity_alias(self) -> str:
        """Return the source entity alias."""
        return self.source.entity.alias

    def target_entity_alias(self) -> str:
        """Return the target entity alias."""
        return self.target.entity.alias

    def referenced_entities(self) -> tuple[str, str]:
        """Return the pair of entity aliases this condition touches."""
        return (
            self.source.entity.alias,
            self.target.entity.alias,
        )

    def to_sql(
        self,
        source_alias: str,
        target_alias: str,
        bind_literals: bool,
        add_parameter: Callable[[object], str],
    ) -> tuple[str, list[object]]:
        """Return the equality ON clause; no parameters are produced."""
        parts = [
            f"{source_alias}.{source_field.name} = {target_alias}.{target_field.name}"
            for source_field, target_field in zip(
                self.source.fields, self.target.fields, strict=True
            )
        ]
        return " AND ".join(parts), []


@dataclass(frozen=True)
class ExpressionJoin:
    """Arbitrary SQL expression join between two entities.

    The expression may reference the source and target table aliases with the
    placeholders ``{source}`` and ``{target}``. Any other placeholder is
    rejected. No literal binding is supported inside the expression; if a
    parameter is needed, the caller must pass it through a separate filter
    predicate. Only ``filter_direction="SINGLE"`` is supported in the first
    version, which ``SemanticRelationship`` enforces at construction.

    ``source_entity`` may equal ``target_entity`` for a self join; the graph
    layer classifies such a single edge as a self reference.
    """

    source_entity: str
    target_entity: str
    expression: str

    def __post_init__(self) -> None:
        """Validate that the expression uses only known placeholders."""
        unknown = _placeholder_tokens(self.expression) - _ALLOWED_PLACEHOLDERS
        if unknown:
            raise ValueError(f"Unsupported placeholders in join expression: {unknown}")

    def source_entity_alias(self) -> str:
        """Return the source entity alias."""
        return self.source_entity

    def target_entity_alias(self) -> str:
        """Return the target entity alias."""
        return self.target_entity

    def referenced_entities(self) -> tuple[str, str]:
        """Return the pair of entity aliases this condition touches."""
        return (self.source_entity, self.target_entity)

    def to_sql(
        self,
        source_alias: str,
        target_alias: str,
        bind_literals: bool,
        add_parameter: Callable[[object], str],
    ) -> tuple[str, list[object]]:
        """Return the expression ON clause; no parameters are produced.

        ``bind_literals`` and ``add_parameter`` are accepted for protocol
        compatibility but ignored: an opaque expression cannot expose its
        literals, so every value in it is inlined in the SQL text.
        """
        rendered = self.expression.replace("{source}", source_alias).replace(
            "{target}", target_alias
        )
        return rendered, []


__all__ = ["EquiJoin", "ExpressionJoin", "JoinCondition"]
