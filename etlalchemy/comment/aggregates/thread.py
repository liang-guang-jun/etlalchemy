"""Thread aggregate: one discussion attached to a commented element."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, replace
from datetime import datetime
from uuid import UUID

from eventsourcing.domain import Aggregate, AggregateCreated, event

from etlalchemy.comment.aggregates.errors import (
    CommentAuthorMismatchError,
    CommentBodyEmptyError,
    CommentBodyTooLongError,
    CommentCycleError,
    DuplicateCommentError,
    InvalidThreadTransitionError,
    MentionsLimitExceededError,
    ThreadDiscardedError,
    ThreadFullError,
    ThreadResolvedError,
    UnknownCommentError,
)
from etlalchemy.comment.aggregates.types import Comment, ThreadStatus

Mentions = tuple[UUID, ...]
"""Users mentioned by a comment, deduplicated, in first-seen order."""


def _normalise_title(title: str | None) -> str:
    """Returns the title without surrounding whitespace, or an empty string."""
    return "" if title is None else title.strip()


def _normalise_mentions(mentions: Iterable[UUID]) -> Mentions:
    """Returns the mentions deduplicated while preserving first-seen order."""
    return tuple(dict.fromkeys(mentions))


def _normalise_body(body: str, max_body_length: int) -> str:
    """Returns the stripped body, rejecting a blank or over-long one."""
    cleaned = body.strip()
    if not cleaned:
        msg = "a comment body must not be blank"
        raise CommentBodyEmptyError(msg)
    if len(cleaned) > max_body_length:
        msg = f"a comment body must not exceed {max_body_length} characters"
        raise CommentBodyTooLongError(msg)
    return cleaned


def _checked_mentions(mentions: Iterable[UUID], max_mentions: int) -> Mentions:
    """Returns the deduplicated mentions, rejecting too many of them."""
    unique = _normalise_mentions(mentions)
    if len(unique) > max_mentions:
        msg = f"a comment must not mention more than {max_mentions} users"
        raise MentionsLimitExceededError(msg)
    return unique


class Thread(Aggregate):
    """Aggregate root that owns every comment of one target.

    Comments are internal entities stored flat in insertion order, so a thread
    loads in one stream and the reply relation is only the ``parent_comment_id``
    link. The status is the lifecycle state machine; it moves ``OPEN`` ->
    ``RESOLVED`` -> ``OPEN`` and any live state -> ``DISCARDED``, which is
    terminal.
    """

    def __init__(
        self,
        target_type: str,
        target_id: UUID,
        author_user_id: UUID,
        author_tenant_id: UUID | None,
        root_comment_id: UUID,
        body: str,
        mentions: Mentions,
        created_at: datetime,
        title: str = "",
    ) -> None:
        """Initialises a thread with its root comment."""
        self.target_type = target_type
        self.target_id = target_id
        self.title = _normalise_title(title)
        self.status = ThreadStatus.OPEN.value
        self.author_user_id = author_user_id
        self.author_tenant_id = author_tenant_id
        self.created_at = created_at
        self.resolved_at: datetime | None = None
        self.resolved_by: UUID | None = None
        self.discarded_at: datetime | None = None
        self.comments: dict[UUID, Comment] = {
            root_comment_id: Comment(
                comment_id=root_comment_id,
                author_user_id=author_user_id,
                author_tenant_id=author_tenant_id,
                parent_comment_id=None,
                body=body.strip(),
                mentions=_normalise_mentions(mentions),
                created_at=created_at,
            ),
        }

    class Event(Aggregate.Event):
        """Base class for events raised by the thread aggregate."""

    @dataclass(frozen=True)
    class Started(AggregateCreated):
        """Recorded when a thread is created with its root comment."""

        target_type: str
        """Type of the commented element."""
        target_id: UUID
        """ID of the commented element."""
        author_user_id: UUID
        """ID of the user who started the thread."""
        author_tenant_id: UUID | None
        """Tenant the author acted in, or ``None``."""
        root_comment_id: UUID
        """ID of the first comment, which has no parent."""
        body: str
        """Body of the root comment."""
        mentions: Mentions
        """Users mentioned by the root comment."""
        created_at: datetime
        """Moment the thread was created."""
        title: str = ""
        """Optional thread title."""

        def __post_init__(self) -> None:
            """Normalises the title and the decoded mention list."""
            object.__setattr__(self, "title", _normalise_title(self.title))
            object.__setattr__(self, "mentions", _normalise_mentions(self.mentions))

    @dataclass(frozen=True)
    class CommentAdded(Event):
        """Recorded when a comment or reply is added to the thread."""

        comment_id: UUID
        """ID of the new comment."""
        author_user_id: UUID
        """ID of the user who wrote the comment."""
        author_tenant_id: UUID | None
        """Tenant the author acted in, or ``None``."""
        parent_comment_id: UUID | None
        """Comment this one replies to, or ``None`` for a root comment."""
        body: str
        """Body of the comment."""
        mentions: Mentions
        """Users mentioned by the comment."""
        created_at: datetime
        """Moment the comment was written."""

        def __post_init__(self) -> None:
            """Normalises the decoded mention list into a tuple."""
            object.__setattr__(self, "mentions", _normalise_mentions(self.mentions))

    @dataclass(frozen=True)
    class CommentEdited(Event):
        """Recorded when the body or the mentions of a comment change."""

        comment_id: UUID
        """ID of the edited comment."""
        author_user_id: UUID
        """ID of the user who wrote the comment."""
        body: str
        """New body of the comment."""
        mentions: Mentions
        """New mentions of the comment."""
        edited_at: datetime
        """Moment of the edit."""

        def __post_init__(self) -> None:
            """Normalises the decoded mention list into a tuple."""
            object.__setattr__(self, "mentions", _normalise_mentions(self.mentions))

    @dataclass(frozen=True)
    class CommentDiscarded(Event):
        """Recorded when a comment is soft-deleted."""

        comment_id: UUID
        """ID of the discarded comment."""
        discarded_at: datetime
        """Moment of the soft delete."""

    @dataclass(frozen=True)
    class Resolved(Event):
        """Recorded when the thread is resolved."""

        by_user_id: UUID
        """ID of the user who resolved the thread."""
        at: datetime
        """Moment of the resolution."""

    @dataclass(frozen=True)
    class Reopened(Event):
        """Recorded when a resolved thread is reopened."""

        by_user_id: UUID
        """ID of the user who reopened the thread."""
        at: datetime
        """Moment of the reopen."""

    @dataclass(frozen=True)
    class Discarded(Event):
        """Recorded when the thread is soft-deleted."""

        by_user_id: UUID
        """ID of the user who discarded the thread."""
        at: datetime
        """Moment of the soft delete."""

    # -- commands -----------------------------------------------------------

    def add_comment(
        self,
        comment_id: UUID,
        author_user_id: UUID,
        author_tenant_id: UUID | None,
        parent_comment_id: UUID | None,
        body: str,
        mentions: Iterable[UUID],
        created_at: datetime,
        max_comments: int,
        max_body_length: int,
        max_mentions: int,
    ) -> None:
        """Adds a comment or a reply, validating the thread limits first."""
        self._ensure_not_discarded()
        self._ensure_open()
        if comment_id in self.comments:
            msg = f"comment {comment_id} already exists in thread {self.id}"
            raise DuplicateCommentError(msg)
        if len(self.comments) >= max_comments:
            msg = f"thread {self.id} already holds {max_comments} comments"
            raise ThreadFullError(msg)
        if parent_comment_id is not None:
            self._validate_parent(comment_id, parent_comment_id)
        cleaned = _normalise_body(body, max_body_length)
        checked = _checked_mentions(mentions, max_mentions)
        self._comment_added(
            comment_id,
            author_user_id,
            author_tenant_id,
            parent_comment_id,
            cleaned,
            checked,
            created_at,
        )

    def edit_comment(
        self,
        comment_id: UUID,
        editor_user_id: UUID,
        is_admin: bool,
        body: str,
        mentions: Iterable[UUID],
        edited_at: datetime,
        max_body_length: int,
        max_mentions: int,
    ) -> None:
        """Changes the body and mentions of a live comment."""
        self._ensure_not_discarded()
        self._ensure_open()
        comment = self.comment_of(comment_id)
        if comment.author_user_id != editor_user_id and not is_admin:
            msg = f"comment {comment_id} was written by another user"
            raise CommentAuthorMismatchError(msg)
        cleaned = _normalise_body(body, max_body_length)
        checked = _checked_mentions(mentions, max_mentions)
        self._comment_edited(comment_id, comment.author_user_id, cleaned, checked, edited_at)

    def discard_comment(self, comment_id: UUID, discarded_at: datetime) -> None:
        """Soft-deletes one live comment."""
        self._ensure_not_discarded()
        self._ensure_open()
        self.comment_of(comment_id)
        self._comment_discarded(comment_id, discarded_at)

    @event(Resolved)
    def resolve(self, by_user_id: UUID, at: datetime) -> None:
        """Marks the thread as resolved."""
        self._ensure_not_discarded()
        if self.status == ThreadStatus.RESOLVED.value:
            msg = f"thread {self.id} is already resolved"
            raise ThreadResolvedError(msg)
        if self.status != ThreadStatus.OPEN.value:
            msg = f"thread {self.id} cannot be resolved from {self.status}"
            raise InvalidThreadTransitionError(msg)
        self.status = ThreadStatus.RESOLVED.value
        self.resolved_at = at
        self.resolved_by = by_user_id

    @event(Reopened)
    def reopen(self, by_user_id: UUID, at: datetime) -> None:
        """Reopens a resolved thread."""
        self._ensure_not_discarded()
        if self.status != ThreadStatus.RESOLVED.value:
            msg = f"thread {self.id} cannot be reopened from {self.status}"
            raise InvalidThreadTransitionError(msg)
        self.status = ThreadStatus.OPEN.value
        self.resolved_at = None
        self.resolved_by = None

    @event(Discarded)
    def discard(self, by_user_id: UUID, at: datetime) -> None:
        """Soft-deletes the thread; the status becomes terminal."""
        self._ensure_not_discarded()
        self.status = ThreadStatus.DISCARDED.value
        self.discarded_at = at

    # -- queries ------------------------------------------------------------

    @property
    def comment_count(self) -> int:
        """Returns the number of comments, including discarded ones."""
        return len(self.comments)

    def comment_of(self, comment_id: UUID) -> Comment:
        """Returns a live comment, rejecting an unknown or discarded one."""
        comment = self.comments.get(comment_id)
        if comment is None or comment.discarded_at is not None:
            msg = f"comment {comment_id} does not exist in thread {self.id}"
            raise UnknownCommentError(msg)
        return comment

    def depth_of(self, comment_id: UUID) -> int:
        """Returns the parent-chain length of a comment; the root comment is 0."""
        comment = self.comments.get(comment_id)
        if comment is None:
            msg = f"comment {comment_id} does not exist in thread {self.id}"
            raise UnknownCommentError(msg)
        depth = 0
        seen = {comment_id}
        while comment.parent_comment_id is not None:
            parent_id = comment.parent_comment_id
            if parent_id in seen:
                break
            seen.add(parent_id)
            parent = self.comments.get(parent_id)
            if parent is None:
                break
            depth += 1
            comment = parent
        return depth

    # -- event bodies -------------------------------------------------------

    @event(CommentAdded)
    def _comment_added(
        self,
        comment_id: UUID,
        author_user_id: UUID,
        author_tenant_id: UUID | None,
        parent_comment_id: UUID | None,
        body: str,
        mentions: Mentions,
        created_at: datetime,
    ) -> None:
        """Stores the new comment in the thread."""
        self.comments[comment_id] = Comment(
            comment_id=comment_id,
            author_user_id=author_user_id,
            author_tenant_id=author_tenant_id,
            parent_comment_id=parent_comment_id,
            body=body,
            mentions=mentions,
            created_at=created_at,
        )

    @event(CommentEdited)
    def _comment_edited(
        self,
        comment_id: UUID,
        author_user_id: UUID,
        body: str,
        mentions: Mentions,
        edited_at: datetime,
    ) -> None:
        """Replaces the body and mentions of the comment."""
        self.comments[comment_id] = replace(
            self.comments[comment_id],
            body=body,
            mentions=mentions,
            edited_at=edited_at,
        )

    @event(CommentDiscarded)
    def _comment_discarded(self, comment_id: UUID, discarded_at: datetime) -> None:
        """Marks the comment as soft-deleted."""
        self.comments[comment_id] = replace(
            self.comments[comment_id],
            discarded_at=discarded_at,
        )

    # -- validation ---------------------------------------------------------

    def _ensure_not_discarded(self) -> None:
        """Rejects every command on a discarded thread."""
        if self.status == ThreadStatus.DISCARDED.value:
            msg = f"thread {self.id} has been discarded"
            raise ThreadDiscardedError(msg)

    def _ensure_open(self) -> None:
        """Rejects a write to a resolved thread."""
        if self.status == ThreadStatus.RESOLVED.value:
            msg = f"thread {self.id} is resolved and must be reopened first"
            raise ThreadResolvedError(msg)

    def _validate_parent(self, comment_id: UUID, parent_comment_id: UUID) -> None:
        """Rejects an unknown, discarded or cyclic parent."""
        if parent_comment_id == comment_id:
            msg = f"comment {comment_id} cannot reply to itself"
            raise CommentCycleError(msg)
        parent = self.comments.get(parent_comment_id)
        if parent is None or parent.discarded_at is not None:
            msg = f"comment {parent_comment_id} does not exist in thread {self.id}"
            raise UnknownCommentError(msg)
        seen = {comment_id, parent_comment_id}
        current = parent
        while current.parent_comment_id is not None:
            ancestor_id = current.parent_comment_id
            if ancestor_id in seen:
                msg = f"reply to comment {parent_comment_id} would create a cycle"
                raise CommentCycleError(msg)
            seen.add(ancestor_id)
            ancestor = self.comments.get(ancestor_id)
            if ancestor is None:
                break
            current = ancestor
