"""Fakes shared by the comment context tests."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID, uuid4

from etlalchemy.comment.ports.authorization import SessionUser
from etlalchemy.iam.aggregates.errors import AuthenticationError


class FakeAuthorization:
    """In-memory stand-in for the IAM authorization port."""

    def __init__(self) -> None:
        """Starts with no session, user or grant."""
        self.sessions: dict[UUID, SessionUser] = {}
        self.active_users: set[UUID] = set()
        self.grants: set[tuple[UUID, str, UUID, str]] = set()

    def add_session(
        self,
        *,
        user_id: UUID | None = None,
        tenant_id: UUID | None = None,
        is_system_admin: bool = False,
    ) -> SessionUser:
        """Records an active session and returns it."""
        session = SessionUser(
            session_id=uuid4(),
            user_id=user_id or uuid4(),
            tenant_id=tenant_id,
            is_system_admin=is_system_admin,
        )
        self.sessions[session.session_id] = session
        self.active_users.add(session.user_id)
        return session

    def grant(self, session: SessionUser, target_type: str, target_id: UUID, action: str) -> None:
        """Records a target-scoped permission for a session."""
        self.grants.add((session.session_id, target_type, target_id, action))

    async def session_user(self, session_id: UUID) -> SessionUser:
        """Returns the session, rejecting an unknown one."""
        session = self.sessions.get(session_id)
        if session is None:
            msg = "the session does not exist"
            raise AuthenticationError(msg)
        return session

    async def user_exists(self, user_id: UUID) -> bool:
        """Returns whether the user was declared active."""
        return user_id in self.active_users

    async def authorize_target(
        self,
        session_id: UUID,
        target_type: str,
        target_id: UUID,
        action: str,
    ) -> bool:
        """Returns whether the exact grant was recorded."""
        return (session_id, target_type, target_id, action) in self.grants


class FakeTargetLookup:
    """In-memory stand-in for the target lookup port."""

    def __init__(self) -> None:
        """Starts with an empty target tree."""
        self.targets: set[tuple[str, UUID]] = set()
        self.tenants: dict[tuple[str, UUID], UUID] = {}

    def add(self, target_type: str, target_id: UUID, tenant_id: UUID | None = None) -> UUID:
        """Declares a target and returns its id."""
        self.targets.add((target_type, target_id))
        if tenant_id is not None:
            self.tenants[(target_type, target_id)] = tenant_id
        return target_id

    async def exists(self, target_type: str, target_id: UUID) -> bool:
        """Returns whether the target was declared."""
        return (target_type, target_id) in self.targets

    async def tenant_of(self, target_type: str, target_id: UUID) -> UUID | None:
        """Returns the tenant declared for the target."""
        return self.tenants.get((target_type, target_id))


@dataclass(frozen=True)
class FakeTarget:
    """A declared target used by the tests."""

    target_type: str
    target_id: UUID
