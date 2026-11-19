"""Authorization port of the comment context.

The comment context never reads the IAM tables itself: every session lookup and
every permission check goes through this protocol, implemented by the assembly
layer with the IAM application and read model.
"""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from etlalchemy.shared.session import SessionUser as SessionUser


class CommentAuthorizationPort(Protocol):
    """Session and permission checks the comment application depends on."""

    async def session_user(self, session_id: UUID) -> SessionUser:
        """Returns the caller of an active, unexpired session.

        Raises:
            AuthenticationError: If the session is unknown, revoked or expired.
        """
        ...

    async def user_exists(self, user_id: UUID) -> bool:
        """Returns whether the user exists and is active."""
        ...

    async def authorize_target(
        self,
        session_id: UUID,
        target_type: str,
        target_id: UUID,
        action: str,
    ) -> bool:
        """Returns whether the caller may perform ``action`` on the target."""
        ...
