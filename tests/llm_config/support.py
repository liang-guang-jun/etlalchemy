"""Fakes shared by the LLM provider context tests."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from uuid import UUID, uuid4

from etlalchemy.iam.aggregates.errors import AuthenticationError
from etlalchemy.llm_config.application import LlmConfigApplication
from etlalchemy.llm_config.ports.authorization import SessionUser
from etlalchemy.llm_config.projection.projection import run_llm_config_projection
from etlalchemy.llm_config.projection.sqlalchemy import SQLAlchemyLlmProviderView
from etlalchemy.llm_config.projection.view import LlmProviderView
from eventsourcing.asyncio.sqlalchemy import AsyncSQLAlchemyDatastore

TRACKING_TABLE = "llm_config_projection_tracking"
"""Tracking table both the view and the projection runner use."""

Sync = Callable[[], Awaitable[None]]
"""Waits until the projection has caught up with the event store."""


@dataclass(frozen=True)
class FakeSecret:
    """A resolved secret with the shape the port expects."""

    value: str
    """The secret itself."""


@asynccontextmanager
async def running_llm_config(
    env: dict[str, str],
    authorization: FakeAuthorization,
    secrets: FakeSecrets,
) -> AsyncIterator[tuple[LlmConfigApplication, LlmProviderView, Sync]]:
    """Runs the context with its projection and yields the application and view.

    The application reads go through the read model, so a test that asserts on
    them needs the projection running; the returned ``sync`` helper waits until
    every written event has been materialised.
    """
    datastore = AsyncSQLAlchemyDatastore(env["SQLALCHEMY_URL"])
    view = SQLAlchemyLlmProviderView(
        datastore=datastore,
        tracking_table=datastore.create_tracking_table(TRACKING_TABLE),
    )
    await view.create_table()
    try:
        async with run_llm_config_projection(env) as runner:
            application = LlmConfigApplication(
                view=runner.view,
                iam=authorization,
                secrets=secrets,
                env=env,
            )
            async with application:

                async def sync() -> None:
                    """Waits until the projection applied every written event."""
                    last = await application.recorder.max_notification_id()
                    if last is not None:
                        await runner.wait(last, timeout=5.0)

                yield application, runner.view, sync
    finally:
        await datastore.close()


class FakeSecrets:
    """In-memory stand-in for the secret resolver port."""

    def __init__(self) -> None:
        """Starts with no known reference."""
        self.values: dict[str, str] = {}

    def add(self, reference: str, value: str) -> None:
        """Registers a resolvable reference."""
        self.values[reference] = value

    async def resolve(self, ref: str) -> FakeSecret:
        """Returns the registered secret, rejecting an unknown reference."""
        value = self.values.get(ref)
        if value is None:
            msg = f"unknown secret reference {ref!r}"
            raise KeyError(msg)
        return FakeSecret(value=value)


class FakeAuthorization:
    """In-memory stand-in for the IAM authorization port."""

    def __init__(self) -> None:
        """Starts with no session, user, group or grant."""
        self.sessions: dict[UUID, SessionUser] = {}
        self.active_users: set[UUID] = set()
        self.groups: set[UUID] = set()
        self.memberships: dict[UUID, set[UUID]] = {}
        self.grants: set[tuple[UUID, str, str]] = set()

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

    def add_user(self, user_id: UUID | None = None) -> UUID:
        """Declares an active user and returns its id."""
        resolved = user_id or uuid4()
        self.active_users.add(resolved)
        return resolved

    def add_group(self, *, parent: UUID | None = None) -> UUID:
        """Declares a live group and optionally nests it under a parent."""
        group_id = uuid4()
        self.groups.add(group_id)
        if parent is not None:
            self.groups.add(parent)
            self.memberships.setdefault(group_id, set()).add(parent)
        return group_id

    def add_member(self, user_id: UUID, group_id: UUID) -> None:
        """Records that a user belongs to a group."""
        self.memberships.setdefault(user_id, set()).add(group_id)

    def grant_write(self, session: SessionUser) -> None:
        """Grants ``llm_provider:write`` to a session."""
        self.grants.add((session.session_id, "llm_provider", "write"))

    async def session_user(self, session_id: UUID) -> SessionUser:
        """Returns the session, rejecting an unknown one."""
        session = self.sessions.get(session_id)
        if session is None:
            msg = "the session does not exist"
            raise AuthenticationError(msg)
        return session

    async def authorize(self, session_id: UUID, resource: str, action: str) -> bool:
        """Returns whether the exact grant was recorded."""
        return (session_id, resource, action) in self.grants

    async def effective_group_ids(self, session_id: UUID) -> frozenset[UUID]:
        """Returns the groups of the session user, following parent links."""
        session = self.sessions.get(session_id)
        if session is None:
            return frozenset()
        found: set[UUID] = set()
        pending = list(self.memberships.get(session.user_id, set()))
        while pending:
            group_id = pending.pop()
            if group_id in found:
                continue
            found.add(group_id)
            pending.extend(self.memberships.get(group_id, set()))
        return frozenset(found)

    async def user_exists(self, user_id: UUID) -> bool:
        """Returns whether the user was declared active."""
        return user_id in self.active_users

    async def group_exists(self, group_id: UUID) -> bool:
        """Returns whether the group was declared."""
        return group_id in self.groups
