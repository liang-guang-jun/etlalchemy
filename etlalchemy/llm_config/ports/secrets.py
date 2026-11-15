"""Secret resolution port of the LLM provider context.

A provider either stores an external ``credential_ref`` or an inline token. The
reference is resolved here, so the context never reads the environment or the
filesystem itself and the assembly layer keeps one resolver for every context.
"""

from __future__ import annotations

from typing import Protocol


class ResolvedSecret(Protocol):
    """A resolved secret; only its value is used, never its rendering."""

    value: str
    """The secret itself."""


class SecretsResolver(Protocol):
    """Resolves a self-describing credential reference."""

    async def resolve(self, ref: str) -> ResolvedSecret:
        """Returns the secret referenced by ``ref``."""
        ...
