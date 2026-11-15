"""Password hashing port used by the IAM application service.

The aggregate never sees a plaintext password: the application hashes it with
Argon2id and passes the resulting string into the ``Identity`` event.
"""

from __future__ import annotations

from pwdlib import PasswordHash


class PasswordHasher:
    """Hashes and verifies passwords with pwdlib's recommended algorithm.

    ``PasswordHash.recommended()`` is Argon2id with the parameters the library
    recommends for the installed version, so upgrading the dependency upgrades the
    parameters without a code change.
    """

    def __init__(self, hasher: PasswordHash | None = None) -> None:
        """Builds a hasher, defaulting to the library-recommended algorithm."""
        self._hasher = hasher or PasswordHash.recommended()

    def hash(self, password: str) -> str:
        """Returns the hash of the given plaintext password."""
        return self._hasher.hash(password)

    def verify(self, password: str, password_hash: str) -> bool:
        """Returns whether the plaintext password matches the stored hash.

        A malformed or unknown hash is treated as a mismatch instead of raising, so
        authentication can answer uniformly.
        """
        try:
            return bool(self._hasher.verify(password, password_hash))
        except Exception:  # pwdlib raises for unknown or malformed hashes
            return False


__all__ = ["PasswordHasher"]
