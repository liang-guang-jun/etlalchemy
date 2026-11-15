"""Errors raised by the shared bearer authentication layer."""

from __future__ import annotations

__all__ = ["InsufficientScopeError", "InvalidTokenError"]


class InvalidTokenError(Exception):
    """Bearer token missing, malformed, expired, revoked or otherwise unusable.

    Delivery layers translate it into the same opaque 401 response, so a client
    never learns why a token was rejected.
    """


class InsufficientScopeError(Exception):
    """The authenticated caller does not hold a scope a delivery layer requires."""
