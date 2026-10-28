"""Logical data types for semantic Fields.

Each type is a frozen dataclass so parameters are validated at construction
time. A Field references one of these classes directly.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class DataType(Protocol):
    """Protocol every logical type implements."""

    def to_string(self) -> str:
        """Return a compact human-readable representation."""
        ...


@dataclass(frozen=True)
class String:
    """Variable-length string, optionally bounded by length."""

    length: int | None = None

    def __post_init__(self) -> None:
        """Validate that length is positive when provided."""
        if self.length is not None and self.length <= 0:
            raise ValueError("String length must be positive")

    def to_string(self) -> str:
        """Render as string or string(n)."""
        return "string" if self.length is None else f"string({self.length})"


@dataclass(frozen=True)
class Integer:
    """Integer number, optionally bounded by bit width."""

    bits: int | None = None

    def __post_init__(self) -> None:
        """Validate that bits is one of the supported widths."""
        if self.bits is not None and self.bits not in (8, 16, 32, 64):
            raise ValueError("Integer bits must be 8, 16, 32 or 64")

    def to_string(self) -> str:
        """Render as int or int(n)."""
        return "int" if self.bits is None else f"int({self.bits})"


@dataclass(frozen=True)
class Float:
    """Floating-point number, optionally bounded by bit width."""

    bits: int | None = None

    def __post_init__(self) -> None:
        """Validate that bits is 32 or 64."""
        if self.bits is not None and self.bits not in (32, 64):
            raise ValueError("Float bits must be 32 or 64")

    def to_string(self) -> str:
        """Render as float or float(n)."""
        return "float" if self.bits is None else f"float({self.bits})"


@dataclass(frozen=True)
class Decimal:
    """Fixed-point number with precision and optional scale."""

    precision: int
    scale: int | None = None

    def __post_init__(self) -> None:
        """Validate precision and scale bounds."""
        if self.precision <= 0:
            raise ValueError("Decimal precision must be positive")
        if self.scale is not None and self.scale > self.precision:
            raise ValueError("Decimal scale cannot exceed precision")

    def to_string(self) -> str:
        """Render as decimal(p) or decimal(p,s)."""
        if self.scale is None:
            return f"decimal({self.precision})"
        return f"decimal({self.precision},{self.scale})"


@dataclass(frozen=True)
class Boolean:
    """Boolean value."""

    def to_string(self) -> str:
        """Render as bool."""
        return "bool"


@dataclass(frozen=True)
class Date:
    """Calendar date without time."""

    def to_string(self) -> str:
        """Render as date."""
        return "date"


@dataclass(frozen=True)
class Timestamp:
    """Timestamp, optionally timezone-aware."""

    timezone: bool = False

    def to_string(self) -> str:
        """Render as timestamp or timestamp_tz."""
        return "timestamp_tz" if self.timezone else "timestamp"


@dataclass(frozen=True)
class Binary:
    """Binary blob, optionally bounded by length."""

    length: int | None = None

    def __post_init__(self) -> None:
        """Validate that length is positive when provided."""
        if self.length is not None and self.length <= 0:
            raise ValueError("Binary length must be positive")

    def to_string(self) -> str:
        """Render as binary or binary(n)."""
        return "binary" if self.length is None else f"binary({self.length})"


@dataclass(frozen=True)
class Json:
    """JSON document."""

    def to_string(self) -> str:
        """Render as json."""
        return "json"


@dataclass(frozen=True)
class Uuid:
    """UUID value."""

    def to_string(self) -> str:
        """Render as uuid."""
        return "uuid"


@dataclass(frozen=True)
class Array:
    """Array of a homogeneous element type."""

    element: DataType

    def to_string(self) -> str:
        """Render as array<element>."""
        return f"array<{self.element.to_string()}>"
