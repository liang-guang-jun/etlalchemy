"""Application service exposing the comment use cases."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from uuid import UUID, uuid4

import structlog
from eventsourcing.application import AggregateNotFoundError
from eventsourcing.asyncio.application import AsyncApplication
from eventsourcing.utils import EnvType

from etlalchemy.comment.aggregates.errors import (
    CommentBodyEmptyError,
    CommentBodyTooLongError,
    CommentValidationError,
    DuplicateThreadError,
    MentionsLimitExceededError,
    UnknownMentionedUserError,
    UnknownTargetError,
    UnknownTargetTypeError,
    UnknownThreadError,
)
from etlalchemy.comment.aggregates.thread import Thread
from etlalchemy.comment.aggregates.types import DEFAULT_TARGET_TYPES
from etlalchemy.comment.ports.authorization import CommentAuthorizationPort, SessionUser
from etlalchemy.comment.ports.target_lookup import TargetLookupPort
from etlalchemy.comment.projection.view import CommentRow, CommentView, ThreadRow
from etlalchemy.iam.aggregates.errors import (
    AuthenticationError,
    PermissionDeniedError,
)
from etlalchemy.shared.logging import get_logger


@dataclass(frozen=True)
class CommentOptions:
    """Policy and pagination settings of the comment context."""

    max_body_length: int = 10_000
    """Maximum length of a comment body."""
    max_title_length: int = 200
    """Maximum length of a thread title."""
    max_mentions_per_comment: int = 20
    """Maximum number of users one comment may mention."""
    max_comments_per_thread: int = 10_000
    """Hard cap on the comments of one thread, including discarded ones."""
    soft_max_reply_depth: int = 0
    """Advisory reply depth; ``0`` disables the warning."""
    depth_warning_message: str = (
        "This reply is at depth {depth}, beyond the suggested {soft_max}; "
        "consider starting a new thread for a deeper discussion."
    )
    """Template of the advisory warning returned for a deep reply."""
    default_page_size: int = 50
    """Page size used when a read does not specify one."""
    max_page_size: int = 200
    """Upper bound of every page size."""
    validate_target_exists: bool = False
    """Whether a write checks that the target exists."""
    enforce_target_tenant: bool = False
    """Whether a write checks a target-scoped permission in IAM."""
    read_requires_session: bool = True
    """Whether reads require a session."""
    allow_multiple_threads: bool = True
    """Whether one target may have more than one live thread."""
    target_types: frozenset[str] = DEFAULT_TARGET_TYPES
    """Target types accepted by the write path."""


@dataclass(frozen=True)
class ThreadCreated:
    """Result of ``create_thread``."""

    thread_id: UUID
    """ID of the new thread."""
    root_comment_id: UUID
    """ID of the first comment."""


@dataclass(frozen=True)
class CommentCreated:
    """Result of ``add_comment``."""

    comment_id: UUID
    """ID of the new comment."""
    depth: int
    """Parent-chain length; the root comment is 0."""
    depth_warning: str | None = None
    """Advisory message when the reply exceeds the soft depth, else ``None``."""


@dataclass(frozen=True)
class ThreadDetail:
    """A thread together with its comments."""

    thread: ThreadRow
    """The thread metadata row."""
    comments: list[CommentRow]
    """The comments of the thread in creation order."""


class CommentApplication(AsyncApplication[UUID]):
    """Application service for the comment context.

    Every write validates the caller through the IAM port, loads the thread
    aggregate and saves the resulting event. Reads go straight to the comment
    read model, filtered by the tenant of the session when one is required.
    """

    name = "comment_application"
    """Application name; the eventsourcing factories derive table names from it."""

    def __init__(
        self,
        view: CommentView,
        iam: CommentAuthorizationPort,
        target_lookup: TargetLookupPort,
        options: CommentOptions | None = None,
        env: EnvType | None = None,
    ) -> None:
        """Wires the read model, the IAM port and the comment options."""
        super().__init__(env=env)
        self._view = view
        self._iam = iam
        self._target_lookup = target_lookup
        self._options = options or CommentOptions()
        self._log: structlog.stdlib.BoundLogger = get_logger("comment.application")

    # -- writes -------------------------------------------------------------

    async def create_thread(
        self,
        session_id: UUID,
        target_type: str,
        target_id: UUID,
        body: str,
        mentions: list[UUID] | None = None,
        title: str = "",
    ) -> ThreadCreated:
        """Starts a thread with its first comment."""
        self._log.info(
            "comment.thread.create start",
            target_type=target_type,
            target_id=str(target_id),
        )
        session = await self._iam.session_user(session_id)
        self._require_target_type(target_type)
        cleaned_body = self._checked_body(body)
        cleaned_title = self._checked_title(title)
        checked_mentions = await self._checked_mentions(mentions)
        if self._options.validate_target_exists and not await self._target_lookup.exists(
            target_type,
            target_id,
        ):
            msg = f"target {target_type}:{target_id} does not exist"
            raise UnknownTargetError(msg)
        if (
            not self._options.allow_multiple_threads
            and await self._view.count_threads_for_target(target_type, target_id) > 0
        ):
            msg = f"target {target_type}:{target_id} already has a thread"
            raise DuplicateThreadError(msg)
        root_comment_id = uuid4()
        thread = Thread(
            target_type=target_type,
            target_id=target_id,
            author_user_id=session.user_id,
            author_tenant_id=session.tenant_id,
            root_comment_id=root_comment_id,
            body=cleaned_body,
            mentions=tuple(checked_mentions),
            created_at=datetime.now(UTC),
            title=cleaned_title,
        )
        await self.save(thread)
        self._log.info("comment.thread.create done", thread_id=str(thread.id))
        return ThreadCreated(thread_id=thread.id, root_comment_id=root_comment_id)

    async def add_comment(
        self,
        session_id: UUID,
        thread_id: UUID,
        body: str,
        parent_comment_id: UUID | None = None,
        mentions: list[UUID] | None = None,
    ) -> CommentCreated:
        """Adds a comment or a reply and reports its depth."""
        self._log.info("comment.comment.add start", thread_id=str(thread_id))
        session = await self._iam.session_user(session_id)
        thread = await self._thread(thread_id)
        depth = 0
        if parent_comment_id is not None:
            thread.comment_of(parent_comment_id)
            depth = thread.depth_of(parent_comment_id) + 1
        checked_mentions = await self._checked_mentions(mentions)
        comment_id = uuid4()
        thread.add_comment(
            comment_id,
            session.user_id,
            session.tenant_id,
            parent_comment_id,
            body,
            tuple(checked_mentions),
            datetime.now(UTC),
            self._options.max_comments_per_thread,
            self._options.max_body_length,
            self._options.max_mentions_per_comment,
        )
        await self.save(thread)
        warning = self._depth_warning(depth)
        self._log.info(
            "comment.comment.add done",
            thread_id=str(thread_id),
            comment_id=str(comment_id),
            depth=depth,
        )
        return CommentCreated(comment_id=comment_id, depth=depth, depth_warning=warning)

    async def edit_comment(
        self,
        session_id: UUID,
        thread_id: UUID,
        comment_id: UUID,
        body: str | None = None,
        mentions: list[UUID] | None = None,
    ) -> None:
        """Changes the body and/or mentions of a comment."""
        self._log.info(
            "comment.comment.edit start",
            thread_id=str(thread_id),
            comment_id=str(comment_id),
        )
        session = await self._iam.session_user(session_id)
        thread = await self._thread(thread_id)
        comment = thread.comment_of(comment_id)
        new_body = comment.body if body is None else body
        checked_mentions = list(
            comment.mentions if mentions is None else await self._checked_mentions(mentions),
        )
        thread.edit_comment(
            comment_id,
            session.user_id,
            session.is_system_admin,
            new_body,
            checked_mentions,
            datetime.now(UTC),
            self._options.max_body_length,
            self._options.max_mentions_per_comment,
        )
        await self.save(thread)
        self._log.info("comment.comment.edit done", comment_id=str(comment_id))

    async def discard_comment(
        self,
        session_id: UUID,
        thread_id: UUID,
        comment_id: UUID,
    ) -> None:
        """Soft-deletes a comment."""
        self._log.info(
            "comment.comment.discard start",
            thread_id=str(thread_id),
            comment_id=str(comment_id),
        )
        session = await self._iam.session_user(session_id)
        thread = await self._thread(thread_id)
        comment = thread.comment_of(comment_id)
        if comment.author_user_id != session.user_id and not session.is_system_admin:
            allowed = await self._iam.authorize_target(
                session.session_id,
                thread.target_type,
                thread.target_id,
                "moderate",
            )
            if not allowed:
                msg = f"the caller may not moderate thread {thread_id}"
                raise PermissionDeniedError(msg)
        thread.discard_comment(comment_id, datetime.now(UTC))
        await self.save(thread)
        self._log.info("comment.comment.discard done", comment_id=str(comment_id))

    async def resolve_thread(self, session_id: UUID, thread_id: UUID) -> None:
        """Marks a thread as resolved."""
        self._log.info("comment.thread.resolve start", thread_id=str(thread_id))
        session = await self._iam.session_user(session_id)
        thread = await self._thread(thread_id)
        await self._require_target_permission(session, thread, "resolve")
        thread.resolve(session.user_id, datetime.now(UTC))
        await self.save(thread)
        self._log.info("comment.thread.resolve done", thread_id=str(thread_id))

    async def reopen_thread(self, session_id: UUID, thread_id: UUID) -> None:
        """Reopens a resolved thread."""
        self._log.info("comment.thread.reopen start", thread_id=str(thread_id))
        session = await self._iam.session_user(session_id)
        thread = await self._thread(thread_id)
        await self._require_target_permission(session, thread, "resolve")
        thread.reopen(session.user_id, datetime.now(UTC))
        await self.save(thread)
        self._log.info("comment.thread.reopen done", thread_id=str(thread_id))

    async def discard_thread(self, session_id: UUID, thread_id: UUID) -> None:
        """Soft-deletes a thread."""
        self._log.info("comment.thread.discard start", thread_id=str(thread_id))
        session = await self._iam.session_user(session_id)
        thread = await self._thread(thread_id)
        await self._require_target_permission(session, thread, "delete")
        thread.discard(session.user_id, datetime.now(UTC))
        await self.save(thread)
        self._log.info("comment.thread.discard done", thread_id=str(thread_id))

    # -- reads --------------------------------------------------------------

    async def get_thread(
        self,
        thread_id: UUID,
        session_id: UUID | None = None,
    ) -> ThreadDetail:
        """Returns a thread with its comments."""
        self._log.debug("comment.thread.get start", thread_id=str(thread_id))
        session = await self._read_session(session_id)
        row = await self._visible_thread(thread_id, session)
        comments = await self._view.list_comments(thread_id)
        self._log.debug("comment.thread.get done", thread_id=str(thread_id))
        return ThreadDetail(thread=row, comments=comments)

    async def list_threads(
        self,
        session_id: UUID | None = None,
        target_type: str | None = None,
        target_id: UUID | None = None,
        author_user_id: UUID | None = None,
        mention_user_id: UUID | None = None,
        status: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[ThreadRow]:
        """Returns live threads, filtered by the given criteria."""
        self._log.debug("comment.thread.list start", status=status)
        session = await self._read_session(session_id)
        size = self._page_size(limit)
        tenant_id = None if session is None else session.tenant_id
        if mention_user_id is not None:
            rows = await self._view.list_threads_mentioning(
                mention_user_id,
                status,
                tenant_id,
                size,
                offset,
            )
        elif author_user_id is not None:
            rows = await self._view.list_threads_by_author(
                author_user_id,
                status,
                tenant_id,
                size,
                offset,
            )
        elif target_type is not None and target_id is not None:
            rows = await self._view.list_threads_for_target(
                target_type,
                target_id,
                status,
                tenant_id,
                size,
                offset,
            )
        elif target_type is not None or target_id is not None:
            msg = "target_type and target_id must be given together"
            raise ValueError(msg)
        else:
            rows = await self._view.list_threads(status, tenant_id, size, offset)
        self._log.debug("comment.thread.list done", threads=len(rows))
        return rows

    async def list_comments(
        self,
        thread_id: UUID,
        session_id: UUID | None = None,
        limit: int | None = None,
        offset: int = 0,
        flatten_after: int | None = None,
        include_discarded: bool = False,
    ) -> list[CommentRow]:
        """Returns the comments of a thread, optionally capping their depth."""
        self._log.debug("comment.comment.list start", thread_id=str(thread_id))
        session = await self._read_session(session_id)
        await self._visible_thread(thread_id, session)
        rows = await self._view.list_comments(
            thread_id,
            include_discarded,
            self._page_size(limit),
            offset,
        )
        if flatten_after is not None and flatten_after >= 0:
            rows = [replace(row, depth=min(row.depth, flatten_after)) for row in rows]
        self._log.debug("comment.comment.list done", comments=len(rows))
        return rows

    # -- helpers ------------------------------------------------------------

    async def _thread(self, thread_id: UUID) -> Thread:
        """Returns a thread aggregate, rejecting an unknown id."""
        try:
            thread: Thread = await self.repository.get(thread_id)
        except AggregateNotFoundError as exc:
            msg = f"thread {thread_id} does not exist"
            raise UnknownThreadError(msg) from exc
        return thread

    async def _thread_row_or_unknown(self, thread_id: UUID) -> ThreadRow:
        """Returns the read-model row of a live thread, rejecting an unknown id."""
        row = await self._view.get_thread(thread_id)
        if row is None:
            msg = f"thread {thread_id} does not exist"
            raise UnknownThreadError(msg)
        return row

    async def _visible_thread(
        self,
        thread_id: UUID,
        session: SessionUser | None,
    ) -> ThreadRow:
        """Returns a thread the session may read."""
        row = await self._thread_row_or_unknown(thread_id)
        if not self._is_visible(row, session):
            msg = f"thread {thread_id} does not exist"
            raise UnknownThreadError(msg)
        return row

    async def _read_session(self, session_id: UUID | None) -> SessionUser | None:
        """Returns the session of a read, or ``None`` when reads are anonymous."""
        if session_id is None:
            if self._options.read_requires_session:
                msg = "a session is required to read comments"
                raise AuthenticationError(msg)
            return None
        return await self._iam.session_user(session_id)

    async def _require_target_permission(
        self,
        session: SessionUser,
        thread: Thread,
        action: str,
    ) -> None:
        """Requires the author, an administrator or a target permission."""
        if session.is_system_admin or thread.author_user_id == session.user_id:
            return
        if await self._iam.authorize_target(
            session.session_id,
            thread.target_type,
            thread.target_id,
            action,
        ):
            return
        msg = f"the caller may not {action} thread {thread.id}"
        raise PermissionDeniedError(msg)

    def _is_visible(self, row: ThreadRow, session: SessionUser | None) -> bool:
        """Returns whether the session may see the thread."""
        if session is None or row.author_tenant_id is None:
            return True
        return row.author_tenant_id == session.tenant_id

    def _require_target_type(self, target_type: str) -> None:
        """Rejects a target type the registry does not declare."""
        if target_type not in self._options.target_types:
            msg = f"target type {target_type!r} is not registered"
            raise UnknownTargetTypeError(msg)

    def _checked_body(self, body: str) -> str:
        """Returns the stripped body, rejecting a blank or over-long one."""
        cleaned = body.strip()
        if not cleaned:
            msg = "a comment body must not be blank"
            raise CommentBodyEmptyError(msg)
        if len(cleaned) > self._options.max_body_length:
            msg = f"a comment body must not exceed {self._options.max_body_length} characters"
            raise CommentBodyTooLongError(msg)
        return cleaned

    def _checked_title(self, title: str) -> str:
        """Returns the stripped title, rejecting an over-long one."""
        cleaned = title.strip()
        if len(cleaned) > self._options.max_title_length:
            msg = f"a thread title must not exceed {self._options.max_title_length} characters"
            raise CommentValidationError(msg)
        return cleaned

    async def _checked_mentions(self, mentions: Sequence[UUID] | None) -> list[UUID]:
        """Deduplicates the mentions and validates every mentioned user."""
        unique = list(dict.fromkeys(mentions or []))
        if len(unique) > self._options.max_mentions_per_comment:
            msg = (
                "a comment must not mention more than "
                f"{self._options.max_mentions_per_comment} users"
            )
            raise MentionsLimitExceededError(msg)
        for user_id in unique:
            if not await self._iam.user_exists(user_id):
                msg = f"mentioned user {user_id} does not exist or is not active"
                raise UnknownMentionedUserError(msg)
        return unique

    def _depth_warning(self, depth: int) -> str | None:
        """Returns the advisory warning for a reply deeper than the soft limit."""
        soft_max = self._options.soft_max_reply_depth
        if soft_max <= 0 or depth <= soft_max:
            return None
        return self._options.depth_warning_message.format(depth=depth, soft_max=soft_max)

    def _page_size(self, limit: int | None) -> int:
        """Clamps the requested page size to the configured bounds."""
        size = self._options.default_page_size if limit is None else limit
        if size <= 0:
            size = self._options.default_page_size
        return min(size, self._options.max_page_size)
