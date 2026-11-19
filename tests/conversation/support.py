"""Helpers shared by the conversation context tests."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from uuid import UUID, uuid4

from etlalchemy.conversation.application import ConversationApplication, ConversationOptions
from etlalchemy.conversation.ports.authorization import SessionUser
from etlalchemy.conversation.projection.projection import run_conversation_projection
from etlalchemy.conversation.projection.sqlalchemy import SQLAlchemyConversationView
from etlalchemy.conversation.projection.view import ConversationView
from etlalchemy.iam.aggregates.errors import AuthenticationError
from eventsourcing.asyncio.sqlalchemy import AsyncSQLAlchemyDatastore

TRACKING_TABLE = "conversation_projection_tracking"
"""Tracking table both the view and the projection runner use."""

Sync = Callable[[], Awaitable[None]]
"""Waits until the projection has caught up with the event store."""


class FakeAuthorization:
    """In-memory stand-in for the IAM authorization port."""

    def __init__(self) -> None:
        """Starts with no session."""
        self.sessions: dict[UUID, SessionUser] = {}

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
        return session

    async def session_user(self, session_id: UUID) -> SessionUser:
        """Returns the session, rejecting an unknown one."""
        session = self.sessions.get(session_id)
        if session is None:
            msg = "the session does not exist"
            raise AuthenticationError(msg)
        return session


@asynccontextmanager
async def running_conversation(
    env: dict[str, str],
    authorization: FakeAuthorization,
    options: ConversationOptions | None = None,
) -> AsyncIterator[tuple[ConversationApplication, ConversationView, Sync]]:
    """Runs the context with its projection and yields the application and view."""
    datastore = AsyncSQLAlchemyDatastore(env["SQLALCHEMY_URL"])
    view = SQLAlchemyConversationView(
        datastore=datastore,
        tracking_table=datastore.create_tracking_table(TRACKING_TABLE),
    )
    await view.create_table()
    try:
        async with run_conversation_projection(env) as runner:
            application = ConversationApplication(
                view=runner.view,
                iam=authorization,
                options=options,
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
