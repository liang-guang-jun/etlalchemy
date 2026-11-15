"""Bearer token verification and session lookup of the MCP delivery layer.

The verification itself belongs to :class:`etlalchemy.app.auth.SessionAuthenticator`;
this module only adapts it to FastMCP, so HTTP and MCP accept exactly the same
tokens and agree on revocation, expiry and credential changes.
"""

from __future__ import annotations

from uuid import UUID

from fastmcp.server.auth import AccessToken, TokenVerifier
from fastmcp.server.dependencies import get_access_token

from etlalchemy.app.auth import InvalidTokenError, SessionAuthenticator
from etlalchemy.app.auth.scopes import permission_to_scope
from etlalchemy.app.mcp.session import context_session_id
from etlalchemy.shared.logging import get_logger

__all__ = ["IamTokenVerifier", "current_session_id"]

SESSION_CLAIM = "session_id"
"""Claim carrying the IAM session id tools use to call the applications."""


class IamTokenVerifier(TokenVerifier):
    """Verifies MCP bearer tokens through the shared IAM authenticator."""

    def __init__(self, authenticator: SessionAuthenticator) -> None:
        """Creates the verifier.

        Args:
            authenticator: Shared verifier that also serves the HTTP API.
        """
        super().__init__()
        self._authenticator = authenticator
        self._log = get_logger("etlalchemy.mcp.auth")

    async def verify_token(self, token: str) -> AccessToken | None:
        """Returns the access token of a valid bearer token, or ``None``.

        FastMCP answers ``None`` with a 401 and the standard ``WWW-Authenticate``
        header, so an unusable token never reaches a tool.

        Args:
            token: Value of the ``Authorization: Bearer`` header.

        Returns:
            The access token, with the session id among its claims.
        """
        try:
            session = await self._authenticator.authenticate(token)
        except InvalidTokenError:
            return None
        except Exception:
            self._log.exception("mcp.token.verify.failed")
            raise
        return AccessToken(
            token=token,
            client_id=str(session.user_id),
            scopes=[permission_to_scope(permission) for permission in session.permissions],
            expires_at=int(session.expires_at.timestamp()),
            subject=str(session.user_id),
            claims={
                SESSION_CLAIM: str(session.session_id),
                "user_id": str(session.user_id),
                "identity_id": str(session.identity_id),
                "tenant_id": str(session.tenant_id) if session.tenant_id is not None else None,
                "is_system_admin": session.is_system_admin,
            },
        )


def current_session_id() -> UUID:
    """Returns the session id of the authenticated MCP caller.

    An in-process call (the agent talking to this very server) carries the
    verified session in the context instead of a token; see
    :mod:`etlalchemy.app.mcp.session`. Every other call reads the claim of the
    verified access token.

    Returns:
        The IAM session id of the caller.

    Raises:
        InvalidTokenError: If the call carries neither a bound session nor a
            verified token, which can only happen when ``mcp.require_auth`` is
            disabled or in a direct unit call.
    """
    bound = context_session_id()
    if bound is not None:
        return bound
    token: AccessToken | None = get_access_token()
    if token is None:
        raise InvalidTokenError("invalid or expired token")
    raw_session_id = (token.claims or {}).get(SESSION_CLAIM)
    try:
        return UUID(str(raw_session_id))
    except ValueError as exc:
        raise InvalidTokenError("invalid or expired token") from exc
