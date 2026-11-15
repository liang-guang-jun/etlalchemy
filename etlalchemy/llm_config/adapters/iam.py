"""IAM adapter of the LLM provider authorization port."""

from __future__ import annotations

from collections import defaultdict
from uuid import UUID

from etlalchemy.iam.application import IamApplication
from etlalchemy.iam.projection.view import GroupMemberRow, GroupRow, IamView
from etlalchemy.llm_config.ports.authorization import SessionUser


class IamLlmConfigAuthorizationAdapter:
    """Implements the LLM provider authorization port with the IAM context."""

    def __init__(self, iam: IamApplication, view: IamView) -> None:
        """Stores the IAM application and its read model."""
        self._iam = iam
        self._view = view

    async def session_user(self, session_id: UUID) -> SessionUser:
        """Returns the caller of an active, unexpired session."""
        session = await self._iam.validate_session(session_id)
        return SessionUser(
            session_id=session.session_id,
            user_id=session.user_id,
            tenant_id=session.tenant_id,
            is_system_admin=session.is_system_admin,
        )

    async def authorize(self, session_id: UUID, resource: str, action: str) -> bool:
        """Delegates the permission check to the IAM context."""
        return await self._iam.authorize(session_id, resource, action)

    async def effective_group_ids(self, session_id: UUID) -> frozenset[UUID]:
        """Returns the groups of the caller, following parent links.

        A group nested in a parent group grants what the parent grants, so the
        walk follows ``parent_group_id`` upwards from every direct membership.
        """
        session = await self._iam.validate_session(session_id)
        if session.tenant_id is None:
            return frozenset()
        groups: list[GroupRow] = await self._view.list_groups(session.tenant_id)
        members: list[GroupMemberRow] = await self._view.list_group_members(
            session.tenant_id,
        )
        parents = {group.group_id: group.parent_group_id for group in groups}
        nested: dict[UUID, set[UUID]] = defaultdict(set)
        direct: set[UUID] = set()
        for member in members:
            if member.member_kind == "user" and member.member_id == session.user_id:
                direct.add(member.group_id)
            elif member.member_kind == "group":
                nested[member.group_id].add(member.member_id)
        found: set[UUID] = set()
        pending = list(direct)
        while pending:
            group_id = pending.pop()
            if group_id in found:
                continue
            found.add(group_id)
            parent = parents.get(group_id)
            if parent is not None:
                pending.append(parent)
            pending.extend(nested.get(group_id, set()))
        return frozenset(found)

    async def user_exists(self, user_id: UUID) -> bool:
        """Returns whether the user exists and is active."""
        row = await self._view.get_user(user_id)
        return row is not None and row.status == "ACTIVE"

    async def group_exists(self, group_id: UUID) -> bool:
        """Returns whether the group exists and is live."""
        row = await self._view.get_group(group_id)
        return row is not None
