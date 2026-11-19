"""Authorization port of the LLM provider context.

The context never reads the IAM tables itself: every session lookup, permission
check and group-membership walk goes through this protocol, implemented by the
assembly layer with the IAM application and read model.
"""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from etlalchemy.shared.session import SessionUser as SessionUser


class LlmConfigAuthorizationPort(Protocol):
    """Session, permission and membership checks the application depends on."""

    async def session_user(self, session_id: UUID) -> SessionUser:
        """Returns the caller of an active, unexpired session.

        Raises:
            AuthenticationError: If the session is unknown, revoked or expired.
        """
        ...

    async def authorize(self, session_id: UUID, resource: str, action: str) -> bool:
        """Returns whether the session holds the ``resource:action`` permission."""
        ...

    async def effective_group_ids(self, session_id: UUID) -> frozenset[UUID]:
        """Returns the groups the caller belongs to, including parent groups."""
        ...

    async def user_exists(self, user_id: UUID) -> bool:
        """Returns whether the user exists and is active."""
        ...

    async def group_exists(self, group_id: UUID) -> bool:
        """Returns whether the group exists, is live and belongs to the caller's tenant."""
        ...
