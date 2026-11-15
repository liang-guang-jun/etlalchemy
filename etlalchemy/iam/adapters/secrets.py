"""Secret resolvers of the IAM context: ``env:`` and ``file:`` references."""

from __future__ import annotations

import os
from pathlib import Path


class EnvSecretsResolver:
    """Resolves ``env:NAME`` and ``file:PATH`` references.

    The resolver is deliberately tiny: a provider configuration stores only the
    reference, and the value is read per authentication so rotating a secret needs
    no event and no restart.
    """

    def __init__(self, file_root: Path | None = None) -> None:
        """Builds a resolver, optionally constrained to a directory for files."""
        self._file_root = file_root

    def resolve(self, reference: str) -> str:
        """Returns the value of an ``env:`` or ``file:`` reference.

        Args:
            reference: A reference such as ``env:OIDC_SECRET`` or ``file:oidc.txt``.

        Returns:
            The resolved secret value.

        Raises:
            LookupError: If the scheme is unknown or the secret cannot be read.
        """
        scheme, separator, target = (reference or "").partition(":")
        if not separator or not target:
            msg = f"invalid secret reference: {reference!r}"
            raise LookupError(msg)
        if scheme == "env":
            value = os.environ.get(target)
            if value is None:
                msg = f"environment variable {target!r} is not set"
                raise LookupError(msg)
            return value
        if scheme == "file":
            path = self._resolve_file(target)
            try:
                return path.read_text(encoding="utf-8").strip()
            except OSError as exc:
                msg = f"cannot read secret file {target!r}: {exc}"
                raise LookupError(msg) from exc
        msg = f"unsupported secret reference scheme: {scheme!r}"
        raise LookupError(msg)

    def _resolve_file(self, target: str) -> Path:
        """Resolves a file reference, keeping it inside the configured root."""
        path = Path(target)
        if self._file_root is None:
            return path
        root = self._file_root.resolve()
        resolved = (root / path).resolve()
        if root not in resolved.parents and resolved != root:
            msg = f"secret file {target!r} escapes the configured root"
            raise LookupError(msg)
        return resolved


__all__ = ["EnvSecretsResolver"]
