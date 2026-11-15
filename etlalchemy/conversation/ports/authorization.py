"""Authorization port of the conversation context.

The conversation context never reads the IAM tables itself: every session lookup
goes through this protocol, implemented by the assembly layer with the IAM
application and read model.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True)
class SessionUser:
    """The active session behind a command, with the caller it belongs to."""

    session_id: UUID
    """ID of the validated session."""
    user_id: UUID
    """ID of the user behind the session."""
    tenant_id: UUID | None
    """Tenant the session acts in, or ``None`` for a tenant-free session."""
    is_system_admin: bool
    """Whether the user holds the system administrator flag."""


class ConversationAuthorizationPort(Protocol):
    """Session checks the conversation application depends on."""

    async def session_user(self, session_id: UUID) -> SessionUser:
        """Returns the caller of an active, unexpired session.

        Raises:
            AuthenticationError: If the session is unknown, revoked or expired.
        """
        ...
