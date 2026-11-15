"""Secret value and provider protocols for the ingestion context."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class SecretValue:
    """A secret that refuses to leak through ``str`` and ``repr``."""

    value: str
    """The actual secret, only reachable through this attribute."""

    def __repr__(self) -> str:
        """Renders the secret without its value."""
        return "SecretValue(***)"

    def __str__(self) -> str:
        """Refuses to render the secret; use ``.value`` explicitly."""
        msg = "SecretValue has no string form; use .value"
        raise TypeError(msg)


class SecretsProvider(Protocol):
    """Resolves one credential scheme, for example ``env`` or ``file``."""

    scheme: str
    """The ``scheme:`` prefix this provider handles."""

    async def get(self, path: str) -> SecretValue:
        """Returns the secret stored at ``path`` under this scheme."""
        ...


class SecretsResolver(Protocol):
    """Resolves a self-describing credential reference."""

    async def resolve(self, ref: str) -> SecretValue:
        """Returns the secret referenced by ``ref``."""
        ...
