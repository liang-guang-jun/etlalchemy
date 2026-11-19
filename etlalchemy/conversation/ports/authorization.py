"""Authorization port of the conversation context.

The conversation context never reads the IAM tables itself: every session lookup
goes through this protocol, implemented by the assembly layer with the IAM
application and read model.
"""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from etlalchemy.shared.session import SessionUser as SessionUser


class ConversationAuthorizationPort(Protocol):
    """Session checks the conversation application depends on."""

    async def session_user(self, session_id: UUID) -> SessionUser:
        """Returns the caller of an active, unexpired session.

        Raises:
            AuthenticationError: If the session is unknown, revoked or expired.
        """
        ...
