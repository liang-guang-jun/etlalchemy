"""Shared bearer authentication layer of the assembly package."""

from __future__ import annotations

from etlalchemy.app.auth.authenticator import (
    TOKEN_MESSAGE,
    TOKEN_PREFIX,
    SessionAuthenticator,
)
from etlalchemy.app.auth.errors import InsufficientScopeError, InvalidTokenError
from etlalchemy.app.auth.scopes import permission_to_scope, scope_covers
from etlalchemy.app.auth.session import AuthSession

__all__ = [
    "TOKEN_MESSAGE",
    "TOKEN_PREFIX",
    "AuthSession",
    "InsufficientScopeError",
    "InvalidTokenError",
    "SessionAuthenticator",
    "permission_to_scope",
    "scope_covers",
]
