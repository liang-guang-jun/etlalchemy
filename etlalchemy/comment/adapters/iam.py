"""IAM adapter of the comment authorization port."""

from __future__ import annotations

from uuid import UUID

from etlalchemy.comment.application import CommentOptions
from etlalchemy.comment.ports.authorization import SessionUser
from etlalchemy.comment.ports.target_lookup import TargetLookupPort
from etlalchemy.iam.aggregates.errors import AuthenticationError
from etlalchemy.iam.application import IamApplication
from etlalchemy.iam.projection.view import IamView


class IamCommentAuthorizationAdapter:
    """Resolves comment sessions and target permissions through IAM.

    A session is validated by the IAM application, which also revokes a session
    whose credential version moved on. When ``enforce_target_tenant`` is off
    (the default) a target permission check is not attempted: most targets have
    no tenant to scope it to, so only the author and administrator rules apply.
    """

    def __init__(
        self,
        iam: IamApplication,
        iam_view: IamView,
        target_lookup: TargetLookupPort,
        options: CommentOptions,
    ) -> None:
        """Wires the IAM application, read model and comment options."""
        self._iam = iam
        self._iam_view = iam_view
        self._target_lookup = target_lookup
        self._options = options

    async def session_user(self, session_id: UUID) -> SessionUser:
        """Returns the caller of an active, unexpired session."""
        session = await self._iam.get_session(session_id)
        user = await self._iam_view.get_user(session.user_id)
        if user is None:
            msg = f"user {session.user_id} does not exist"
            raise AuthenticationError(msg)
        return SessionUser(
            session_id=session.session_id,
            user_id=session.user_id,
            tenant_id=session.tenant_id,
            is_system_admin=user.is_system_admin,
        )

    async def user_exists(self, user_id: UUID) -> bool:
        """Returns whether the user exists and is active."""
        user = await self._iam_view.get_user(user_id)
        return user is not None and user.status == "ACTIVE"

    async def authorize_target(
        self,
        session_id: UUID,
        target_type: str,
        target_id: UUID,
        action: str,
    ) -> bool:
        """Returns whether the caller may perform ``action`` on the target."""
        if not self._options.enforce_target_tenant:
            return True
        tenant_id = await self._target_lookup.tenant_of(target_type, target_id)
        if tenant_id is None:
            return False
        return await self._iam.authorize(
            session_id,
            f"comment:{target_type}:{action}",
            "write",
        )
