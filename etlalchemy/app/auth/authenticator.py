"""Single bearer token verification entry point for every delivery layer.

Both the HTTP API and the MCP server call :meth:`SessionAuthenticator.authenticate`,
so session validity, expiry, revocation, credential changes and permission
recomputation have exactly one implementation.
"""

from __future__ import annotations

from uuid import UUID

from etlalchemy.app.auth.errors import InvalidTokenError
from etlalchemy.app.auth.session import AuthSession
from etlalchemy.iam.aggregates.errors import (
    AuthenticationError,
    SessionExpiredError,
    SessionRevokedError,
)
from etlalchemy.iam.application import IamApplication
from etlalchemy.shared.logging import get_logger

__all__ = ["TOKEN_MESSAGE", "TOKEN_PREFIX", "SessionAuthenticator"]

TOKEN_PREFIX = "iam_sess_"
"""Prefix of every bearer token; the rest of the value is the session id."""

TOKEN_MESSAGE = "invalid or expired token"
"""Response message shared by every rejection, so no failure reason leaks."""

_UNUSABLE_SESSION_ERRORS = (AuthenticationError, SessionRevokedError, SessionExpiredError)


class SessionAuthenticator:
    """Turns an opaque bearer token into an :class:`AuthSession`."""

    def __init__(
        self,
        iam: IamApplication,
        *,
        token_prefix: str = TOKEN_PREFIX,
    ) -> None:
        """Creates the authenticator.

        Args:
            iam: IAM application that owns the sessions.
            token_prefix: Prefix every accepted token starts with.
        """
        self._iam = iam
        self._prefix = token_prefix
        self._log = get_logger("etlalchemy.auth")

    @property
    def token_prefix(self) -> str:
        """Returns the prefix accepted tokens start with."""
        return self._prefix

    def format_token(self, session_id: UUID) -> str:
        """Renders the bearer token of a session.

        Args:
            session_id: Id of the session to address.

        Returns:
            The token value, without the ``Bearer`` scheme.
        """
        return f"{self._prefix}{session_id}"

    def extract_session_id(self, raw_token: str) -> UUID:
        """Reads the session id out of a bearer token.

        Args:
            raw_token: Value of the ``Authorization: Bearer`` header, without the
                scheme.

        Returns:
            The session id the token addresses.

        Raises:
            InvalidTokenError: If the prefix is missing or the rest is not a UUID.
        """
        if not raw_token or not raw_token.startswith(self._prefix):
            raise InvalidTokenError(TOKEN_MESSAGE)
        try:
            return UUID(raw_token.removeprefix(self._prefix))
        except ValueError as exc:
            raise InvalidTokenError(TOKEN_MESSAGE) from exc

    async def authenticate(self, raw_token: str) -> AuthSession:
        """Validates a bearer token and returns the caller it represents.

        Args:
            raw_token: Value of the ``Authorization: Bearer`` header, without the
                scheme.

        Returns:
            The authenticated session, including its live permissions.

        Raises:
            InvalidTokenError: If the token is malformed or the session is no
                longer usable. The reason is logged, never returned.
        """
        session_id = self.extract_session_id(raw_token)
        try:
            reference = await self._iam.validate_session(session_id)
        except _UNUSABLE_SESSION_ERRORS as exc:
            self._log.info(
                "auth.token.rejected",
                session_id=str(session_id),
                reason=type(exc).__name__,
            )
            raise InvalidTokenError(TOKEN_MESSAGE) from exc
        permissions = await self._iam.effective_permissions(session_id)
        return AuthSession(
            session_id=reference.session_id,
            user_id=reference.user_id,
            identity_id=reference.identity_id,
            tenant_id=reference.tenant_id,
            expires_at=reference.expires_at,
            is_system_admin=reference.is_system_admin,
            permissions=frozenset(permissions),
        )
