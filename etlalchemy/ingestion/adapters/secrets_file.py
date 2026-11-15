"""Secrets provider backed by files."""

from __future__ import annotations

import asyncio
from pathlib import Path

from etlalchemy.ingestion.ports.secrets import SecretValue


class FileSecretsProvider:
    """Reads secrets from files, optionally rooted under a directory."""

    scheme = "file"
    """The ``scheme:`` prefix this provider handles."""

    def __init__(self, root: Path | None = None) -> None:
        """Stores an optional root used to resolve relative paths."""
        self._root = root

    async def get(self, path: str) -> SecretValue:
        """Returns the stripped contents of the file at ``path``."""
        resolved = Path(path)
        if self._root is not None and not resolved.is_absolute():
            resolved = self._root / resolved
        text = await asyncio.to_thread(resolved.read_text, encoding="utf-8")
        return SecretValue(text.strip())
