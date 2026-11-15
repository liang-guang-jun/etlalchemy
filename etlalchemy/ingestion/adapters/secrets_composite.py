"""Credential resolver that routes by the reference's scheme."""

from __future__ import annotations

from collections.abc import Mapping

from etlalchemy.ingestion.aggregates.errors import UnsupportedCredentialSchemeError
from etlalchemy.ingestion.ports.secrets import SecretsProvider, SecretValue


class CompositeSecretsResolver:
    """Dispatches ``scheme:path`` references to the matching provider."""

    def __init__(self, providers: Mapping[str, SecretsProvider]) -> None:
        """Registers the providers keyed by their scheme."""
        self._providers = dict(providers)

    async def resolve(self, ref: str) -> SecretValue:
        """Returns the secret referenced by ``ref``."""
        scheme, separator, path = ref.partition(":")
        if not separator or scheme not in self._providers:
            msg = f"Unsupported credential reference: {ref!r}"
            raise UnsupportedCredentialSchemeError(msg)
        return await self._providers[scheme].get(path)
