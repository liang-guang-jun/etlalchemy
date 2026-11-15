"""Secrets provider backed by process environment variables."""

from __future__ import annotations

import os

from etlalchemy.ingestion.ports.secrets import SecretValue


class EnvSecretsProvider:
    """Reads secrets from ``os.environ``."""

    scheme = "env"
    """The ``scheme:`` prefix this provider handles."""

    async def get(self, path: str) -> SecretValue:
        """Returns the environment variable named ``path``."""
        return SecretValue(os.environ[path])
