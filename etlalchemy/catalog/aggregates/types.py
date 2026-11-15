"""Canonical data type value object shared by the catalog aggregates."""

from __future__ import annotations

import re
from dataclasses import dataclass

from etlalchemy.catalog.aggregates.errors import InvalidDataTypeError

_CANONICAL: frozenset[str] = frozenset(
    {
        "boolean",
        "smallint",
        "integer",
        "bigint",
        "float",
        "double",
        "decimal",
        "string",
        "varchar",
        "char",
        "text",
        "date",
        "timestamp",
        "timestamptz",
        "json",
        "binary",
        "uuid",
    }
)

_PARAMETERIZED: frozenset[str] = frozenset({"decimal", "varchar", "char"})

_ALIASES: dict[str, str] = {
    "str": "string",
    "int": "integer",
    "int4": "integer",
    "int2": "smallint",
    "int8": "bigint",
    "bool": "boolean",
    "float4": "float",
    "float8": "double",
    "numeric": "decimal",
    "datetime": "timestamp",
    "jsonb": "json",
    "bytea": "binary",
    "blob": "binary",
}

_TYPE_RE = re.compile(
    r"^(?P<base>[a-z_][a-z0-9_]*)"
    r"\s*(?:\(\s*(?P<args>[0-9]+(?:\s*,\s*[0-9]+)*)\s*\))?$"
)


@dataclass(frozen=True, slots=True)
class DataType:
    """A normalised data type: a canonical base plus optional integer parameters."""

    base: str
    """Canonical base type, for example ``decimal`` or ``varchar``."""
    args: tuple[int, ...] = ()
    """Integer parameters of a parameterised type, for example ``(10, 2)``."""

    def __post_init__(self) -> None:
        """Validates the base type and normalises the parameters to a tuple."""
        base = self.base.strip().lower()
        if base not in _CANONICAL:
            msg = f"Unknown data type: {base!r}"
            raise InvalidDataTypeError(msg)
        object.__setattr__(self, "base", base)
        object.__setattr__(self, "args", tuple(self.args))

    def __str__(self) -> str:
        """Returns the canonical text form, for example ``varchar(255)``."""
        if self.args:
            return f"{self.base}({','.join(str(arg) for arg in self.args)})"
        return self.base

    @classmethod
    def parse(cls, raw: str | DataType) -> DataType:
        """Parses an arbitrary spelling into a canonical :class:`DataType`."""
        if isinstance(raw, DataType):
            return raw
        text = raw.strip().lower()
        match = _TYPE_RE.match(text)
        if match is None:
            msg = f"Malformed data type: {raw!r}"
            raise InvalidDataTypeError(msg)

        base = _ALIASES.get(match.group("base"), match.group("base"))
        if base not in _CANONICAL:
            msg = f"Unknown data type {raw!r}; expected one of {sorted(_CANONICAL)}"
            raise InvalidDataTypeError(msg)

        raw_args = match.group("args")
        args = tuple(int(part) for part in raw_args.split(",")) if raw_args is not None else ()
        if args and base not in _PARAMETERIZED:
            msg = f"Data type {base!r} does not accept parameters"
            raise InvalidDataTypeError(msg)
        return cls(base=base, args=args)
