"""Ports of the IAM context: the secret resolver used for provider credentials."""

from __future__ import annotations

from typing import Protocol


class SecretsResolver(Protocol):
    """Resolves a secret reference such as ``env:OIDC_SECRET`` to its value."""

    def resolve(self, reference: str) -> str:
        """Returns the secret value the reference points at.

        Raises:
            LookupError: If the reference cannot be resolved.
        """
        ...


__all__ = ["SecretsResolver"]
