"""Read model interface of the comment context."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from eventsourcing.persistence import Tracking

from etlalchemy._vendor.eventsourcing.asyncio.persistence import AsyncTrackingRecorder


def as_uuid(value: UUID | str) -> UUID:
    """Returns the given value as a :class:`UUID`."""
    return value if isinstance(value, UUID) else UUID(value)


@dataclass(frozen=True)
class ThreadRow:
    """A comment thread as stored in the read model."""

    thread_id: UUID
    """ID of the thread aggregate."""
    target_type: str
    """Type of the commented element."""
    target_id: UUID
    """ID of the commented element."""
    title: str
    """Optional thread title."""
    status: str
    """One of ``OPEN``, ``RESOLVED`` or ``DISCARDED``."""
    author_user_id: UUID
    """ID of the user who started the thread."""
    author_tenant_id: UUID | None
    """Tenant the thread was started in, or ``None``."""
    comment_count: int
    """Number of live comments."""
    last_activity_at: datetime
    """Moment of the last comment, resolution or reopen."""
    created_at: datetime
    """Moment the thread was created."""
    resolved_at: datetime | None
    """Moment of the last resolution, or ``None``."""
    resolved_by: UUID | None
    """ID of the user who resolved the thread, or ``None``."""


@dataclass(frozen=True)
class CommentRow:
    """One comment of a thread as stored in the read model."""

    comment_id: UUID
    """ID of the comment."""
    thread_id: UUID
    """ID of the thread that owns the comment."""
    parent_comment_id: UUID | None
    """Comment this one replies to, or ``None`` for a root comment."""
    author_user_id: UUID
    """ID of the user who wrote the comment."""
    author_tenant_id: UUID | None
    """Tenant the author acted in, or ``None``."""
    body: str
    """Plain-text body of the comment."""
    mentions: list[UUID]
    """Users mentioned by the comment."""
    created_at: datetime
    """Moment the comment was written."""
    edited_at: datetime | None
    """Moment of the last edit, or ``None``."""
    discarded_at: datetime | None
    """Moment of the soft delete, or ``None`` while the comment is live."""
    depth: int = 0
    """Parent-chain length; the root comment is 0.

    Computed when the comment is read, never stored. When the parent lies
    outside the requested page the depth restarts at 0.
    """


class CommentView(AsyncTrackingRecorder, ABC):
    """Read model of the comment context."""

    @abstractmethod
    async def create_table(self) -> None:
        """Creates the tracking table and the view tables if they do not exist."""

    # -- writes -------------------------------------------------------------

    @abstractmethod
    async def register_thread(
        self,
        thread_id: UUID,
        target_type: str,
        target_id: UUID,
        title: str,
        author_user_id: UUID,
        author_tenant_id: UUID | None,
        root_comment_id: UUID,
        body: str,
        mentions: list[UUID],
        created_at: datetime,
        tracking: Tracking,
    ) -> None:
        """Registers a thread together with its root comment."""

    @abstractmethod
    async def add_comment(
        self,
        comment_id: UUID,
        thread_id: UUID,
        parent_comment_id: UUID | None,
        author_user_id: UUID,
        author_tenant_id: UUID | None,
        body: str,
        mentions: list[UUID],
        created_at: datetime,
        tracking: Tracking,
    ) -> None:
        """Registers a comment and refreshes the thread activity."""

    @abstractmethod
    async def edit_comment(
        self,
        comment_id: UUID,
        thread_id: UUID,
        author_user_id: UUID,
        body: str,
        mentions: list[UUID],
        edited_at: datetime,
        tracking: Tracking,
    ) -> None:
        """Replaces the body and mentions of a comment."""

    @abstractmethod
    async def discard_comment(
        self,
        comment_id: UUID,
        thread_id: UUID,
        discarded_at: datetime,
        tracking: Tracking,
    ) -> None:
        """Soft-deletes a comment and refreshes the live comment count."""

    @abstractmethod
    async def resolve_thread(
        self,
        thread_id: UUID,
        resolved_by: UUID,
        at: datetime,
        tracking: Tracking,
    ) -> None:
        """Marks a thread as resolved."""

    @abstractmethod
    async def reopen_thread(
        self,
        thread_id: UUID,
        at: datetime,
        tracking: Tracking,
    ) -> None:
        """Reopens a resolved thread."""

    @abstractmethod
    async def discard_thread(
        self,
        thread_id: UUID,
        at: datetime,
        tracking: Tracking,
    ) -> None:
        """Soft-deletes a thread."""

    # -- reads --------------------------------------------------------------

    @abstractmethod
    async def get_thread(self, thread_id: UUID) -> ThreadRow | None:
        """Returns one live thread, or ``None``."""

    @abstractmethod
    async def list_threads_for_target(
        self,
        target_type: str,
        target_id: UUID,
        status: str | None = None,
        tenant_id: UUID | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[ThreadRow]:
        """Returns the live threads of one target, most recently active first."""

    @abstractmethod
    async def list_threads(
        self,
        status: str | None = None,
        tenant_id: UUID | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[ThreadRow]:
        """Returns every live thread, most recently active first."""

    @abstractmethod
    async def list_threads_by_author(
        self,
        author_user_id: UUID,
        status: str | None = None,
        tenant_id: UUID | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[ThreadRow]:
        """Returns the live threads started by a user."""

    @abstractmethod
    async def list_threads_mentioning(
        self,
        user_id: UUID,
        status: str | None = None,
        tenant_id: UUID | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[ThreadRow]:
        """Returns the live threads with a comment that mentions a user."""

    @abstractmethod
    async def get_comment(self, comment_id: UUID) -> CommentRow | None:
        """Returns one live comment, or ``None``."""

    @abstractmethod
    async def list_comments(
        self,
        thread_id: UUID,
        include_discarded: bool = False,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[CommentRow]:
        """Returns the comments of a thread in creation order, with depths."""

    @abstractmethod
    async def count_threads_for_target(self, target_type: str, target_id: UUID) -> int:
        """Returns the number of live threads of one target."""
