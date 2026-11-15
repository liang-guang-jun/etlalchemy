"""FastAPI dependencies that turn a bearer token into an authenticated caller."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from dependency_injector.wiring import Provide, inject
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer

from etlalchemy.app.auth import (
    TOKEN_MESSAGE,
    AuthSession,
    InvalidTokenError,
    SessionAuthenticator,
)
from etlalchemy.app.bootstrap import Container

__all__ = [
    "configure_token_path",
    "get_auth_session",
    "get_bearer_token",
    "get_session_id",
    "oauth2_scheme",
    "token_path",
]

TOKEN_PATH = "/iam/auth/token"
"""Path of the OAuth2 password grant endpoint, relative to the API prefix."""

oauth2_scheme = OAuth2PasswordBearer(tokenUrl=TOKEN_PATH, auto_error=False)
"""Extracts ``Authorization: Bearer`` without parsing the value.

``auto_error=False`` lets :func:`get_auth_session` answer every rejection with the
same opaque message. Swagger UI reads ``tokenUrl`` from this object to render its
"Authorize" button.
"""


def token_path(prefix: str) -> str:
    """Returns the login path the Swagger password flow advertises.

    Args:
        prefix: API prefix the routers are mounted under, for example ``/api``.

    Returns:
        The login path, for example ``/api/iam/auth/token``.
    """
    return f"{prefix}{TOKEN_PATH}"


def configure_token_path(prefix: str) -> str:
    """Points the shared OAuth2 scheme at the prefixed login endpoint.

    The scheme is a module-level object because the route dependencies are
    wired at import time, so the prefix the application resolves is applied here
    instead of being baked into :data:`TOKEN_PATH`.

    Args:
        prefix: API prefix the routers are mounted under, for example ``/api``.

    Returns:
        The login path the Swagger UI now advertises.
    """
    path = token_path(prefix)
    model: Any = oauth2_scheme.model
    flows = model.flows
    if flows.password is not None:
        flows.password.tokenUrl = path
    return path


def _unauthorized() -> HTTPException:
    """Returns the single 401 response every rejected token produces."""
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=TOKEN_MESSAGE,
        headers={"WWW-Authenticate": "Bearer"},
    )


@inject
async def get_auth_session(
    raw_token: str | None = Depends(oauth2_scheme),
    authenticator: SessionAuthenticator = Depends(  # noqa: B008
        Provide[Container.session_authenticator]
    ),
) -> AuthSession:
    """Resolves the bearer token of the request into an authenticated session.

    Args:
        raw_token: Value extracted from the ``Authorization`` header, if any.
        authenticator: Shared verifier of the IAM context.

    Returns:
        The authenticated caller.

    Raises:
        HTTPException: 401 when the header is missing or the token is unusable.
    """
    if not raw_token:
        raise _unauthorized()
    try:
        return await authenticator.authenticate(raw_token)
    except InvalidTokenError as exc:
        raise _unauthorized() from exc


async def get_session_id(auth: AuthSession = Depends(get_auth_session)) -> UUID:  # noqa: B008
    """Returns the session id of the authenticated caller."""
    return auth.session_id


async def get_bearer_token(raw_token: str | None = Depends(oauth2_scheme)) -> str:
    """Returns the raw bearer token, for callers that forward it.

    The agent runtime forwards the caller's token to the MCP endpoint, so it
    needs the value and not just the resolved session.

    Args:
        raw_token: Value extracted from the ``Authorization`` header, if any.

    Returns:
        The token without the ``Bearer`` scheme.

    Raises:
        HTTPException: 401 when the header is missing.
    """
    if not raw_token:
        raise _unauthorized()
    return raw_token
