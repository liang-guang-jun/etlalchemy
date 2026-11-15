"""IAM adapter of the conversation authorization port."""

from __future__ import annotations

from uuid import UUID

from etlalchemy.conversation.ports.authorization import SessionUser
from etlalchemy.iam.application import IamApplication


class IamConversationAuthorizationAdapter:
    """Implements the conversation authorization port with the IAM application."""

    def __init__(self, iam: IamApplication) -> None:
        """Stores the IAM application."""
        self._iam = iam

    async def session_user(self, session_id: UUID) -> SessionUser:
        """Returns the caller of an active, unexpired session."""
        session = await self._iam.validate_session(session_id)
        return SessionUser(
            session_id=session.session_id,
            user_id=session.user_id,
            tenant_id=session.tenant_id,
            is_system_admin=session.is_system_admin,
        )
