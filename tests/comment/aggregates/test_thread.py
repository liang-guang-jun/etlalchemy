"""Tests for the comment thread aggregate."""

from __future__ import annotations

from dataclasses import fields, is_dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
from etlalchemy.comment.aggregates.errors import (
    CommentAuthorMismatchError,
    CommentBodyEmptyError,
    CommentBodyTooLongError,
    CommentCycleError,
    InvalidThreadTransitionError,
    MentionsLimitExceededError,
    ThreadDiscardedError,
    ThreadFullError,
    ThreadResolvedError,
    UnknownCommentError,
)
from etlalchemy.comment.aggregates.thread import Thread
from etlalchemy.comment.aggregates.types import ThreadStatus

NOW = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
AUTHOR = uuid4()
TENANT = uuid4()

EVENT_CLASSES = [
    Thread.Started,
    Thread.CommentAdded,
    Thread.CommentEdited,
    Thread.CommentDiscarded,
    Thread.Resolved,
    Thread.Reopened,
    Thread.Discarded,
]


def new_thread(*, title: str = "", body: str = "root body") -> Thread:
    """Returns a thread with its creation event still pending."""
    return Thread(
        target_type="table",
        target_id=uuid4(),
        author_user_id=AUTHOR,
        author_tenant_id=TENANT,
        root_comment_id=uuid4(),
        body=body,
        mentions=(),
        created_at=NOW,
        title=title,
    )


def make_thread() -> Thread:
    """Returns a thread with its creation event already collected."""
    thread = new_thread()
    thread.collect_events()
    return thread


def add_comment(
    thread: Thread,
    *,
    body: str = "reply",
    parent: UUID | None = None,
    mentions: tuple[UUID, ...] = (),
    max_comments: int = 100,
    max_body_length: int = 10_000,
    max_mentions: int = 20,
) -> UUID:
    """Adds a comment to the thread and returns its id."""
    comment_id = uuid4()
    thread.add_comment(
        comment_id,
        AUTHOR,
        TENANT,
        parent,
        body,
        mentions,
        NOW,
        max_comments,
        max_body_length,
        max_mentions,
    )
    return comment_id


def replay(events: list[Any]) -> Thread:
    """Rebuilds a thread by applying the given events in order."""
    aggregate: Any = None
    for event in events:
        aggregate = event.mutate(aggregate)
    assert isinstance(aggregate, Thread)
    return aggregate


def test_creating_a_thread_records_the_root_comment() -> None:
    """Creating a thread stores its target, title and first comment."""
    root_id = uuid4()
    thread = Thread(
        target_type="table",
        target_id=uuid4(),
        author_user_id=AUTHOR,
        author_tenant_id=TENANT,
        root_comment_id=root_id,
        body="  root body  ",
        mentions=[AUTHOR, AUTHOR],
        created_at=NOW,
        title="  pricing  ",
    )

    assert thread.status == ThreadStatus.OPEN.value
    assert thread.title == "pricing"
    assert thread.author_user_id == AUTHOR
    assert thread.comment_count == 1
    root = thread.comments[root_id]
    assert root.parent_comment_id is None
    assert root.body == "root body"
    assert root.mentions == (AUTHOR,)

    events = thread.collect_events()
    assert len(events) == 1
    assert isinstance(events[0], Thread.Started)
    assert events[0].root_comment_id == root_id
    assert events[0].originator_version == 1


def test_events_are_frozen_dataclasses() -> None:
    """Every event is a frozen dataclass so it can be replayed safely."""
    for event_class in EVENT_CLASSES:
        assert is_dataclass(event_class)
        assert event_class.__dataclass_params__.frozen
        assert fields(event_class)


def test_replaying_the_events_rebuilds_the_thread() -> None:
    """Comments, depths and the resolved state survive a replay."""
    thread = new_thread()
    events = list(thread.collect_events())
    root = next(iter(thread.comments))
    first = add_comment(thread, parent=root)
    second = add_comment(thread, parent=first)
    thread.resolve(AUTHOR, NOW)
    events.extend(thread.collect_events())

    rebuilt = replay(events)

    assert rebuilt.comments == thread.comments
    assert rebuilt.status == ThreadStatus.RESOLVED.value
    assert rebuilt.resolved_by == AUTHOR
    assert rebuilt.resolved_at == NOW
    assert rebuilt.depth_of(second) == 2


def test_replies_derive_their_depth_from_the_parent_chain() -> None:
    """The root comment is at depth 0 and every reply adds one level."""
    thread = make_thread()
    root = next(iter(thread.comments))
    first = add_comment(thread, parent=root)
    second = add_comment(thread, parent=first)

    assert thread.depth_of(root) == 0
    assert thread.depth_of(first) == 1
    assert thread.depth_of(second) == 2


def test_a_very_deep_chain_is_still_accepted() -> None:
    """Depth is not a hard limit; a 100-level reply chain stays writable."""
    thread = make_thread()
    parent = next(iter(thread.comments))
    for _ in range(100):
        parent = add_comment(thread, parent=parent, max_comments=200)

    assert thread.depth_of(parent) == 100
    assert thread.comment_count == 101


def test_a_resolved_thread_rejects_writes_until_reopened() -> None:
    """A resolved thread refuses comments and edits."""
    thread = make_thread()
    thread.resolve(AUTHOR, NOW)
    thread.collect_events()
    version = thread.version

    with pytest.raises(ThreadResolvedError):
        add_comment(thread)
    with pytest.raises(ThreadResolvedError):
        thread.resolve(AUTHOR, NOW)

    assert thread.version == version
    assert thread.pending_events == []

    thread.reopen(AUTHOR, NOW)
    assert thread.status == ThreadStatus.OPEN.value
    assert thread.resolved_at is None
    assert thread.resolved_by is None
    add_comment(thread)


def test_a_discarded_thread_is_terminal() -> None:
    """A discarded thread rejects every command without changing its state."""
    thread = make_thread()
    thread.discard(AUTHOR, NOW)
    version = thread.version

    with pytest.raises(ThreadDiscardedError):
        add_comment(thread)
    with pytest.raises(ThreadDiscardedError):
        thread.resolve(AUTHOR, NOW)
    with pytest.raises(ThreadDiscardedError):
        thread.discard(AUTHOR, NOW)

    assert thread.status == ThreadStatus.DISCARDED.value
    assert thread.discarded_at == NOW
    assert thread.version == version


def test_an_invalid_status_transition_is_rejected() -> None:
    """Reopening an open thread is not a valid transition."""
    thread = make_thread()

    with pytest.raises(InvalidThreadTransitionError):
        thread.reopen(AUTHOR, NOW)


def test_reply_parent_must_be_live_in_the_same_thread() -> None:
    """An unknown or discarded parent is rejected."""
    thread = make_thread()

    with pytest.raises(UnknownCommentError):
        add_comment(thread, parent=uuid4())

    discarded = add_comment(thread)
    thread.discard_comment(discarded, NOW)
    with pytest.raises(UnknownCommentError):
        add_comment(thread, parent=discarded)


def test_a_comment_cannot_reply_to_itself() -> None:
    """A comment id used as its own parent is a cycle."""
    thread = make_thread()
    comment_id = uuid4()

    with pytest.raises(CommentCycleError):
        thread.add_comment(
            comment_id,
            AUTHOR,
            TENANT,
            comment_id,
            "body",
            (),
            NOW,
            100,
            10_000,
            20,
        )


def test_the_thread_rejects_more_comments_than_allowed() -> None:
    """The hard cap counts the root comment too."""
    thread = make_thread()

    with pytest.raises(ThreadFullError):
        add_comment(thread, max_comments=1)


def test_bodies_are_stripped_and_bounded() -> None:
    """A blank body and an over-long body are rejected."""
    thread = make_thread()
    comment_id = add_comment(thread, body="  hello  ")
    assert thread.comments[comment_id].body == "hello"

    with pytest.raises(CommentBodyEmptyError):
        add_comment(thread, body="   ")
    with pytest.raises(CommentBodyTooLongError):
        add_comment(thread, body="x" * 11, max_body_length=10)


def test_mentions_are_deduplicated_and_bounded() -> None:
    """Mentions keep their first-seen order and respect the limit."""
    thread = make_thread()
    other = uuid4()
    comment_id = add_comment(thread, mentions=(AUTHOR, other, AUTHOR))

    assert thread.comments[comment_id].mentions == (AUTHOR, other)

    with pytest.raises(MentionsLimitExceededError):
        add_comment(thread, mentions=(AUTHOR, other), max_mentions=1)


def test_only_the_author_or_an_admin_edits_a_comment() -> None:
    """Editing checks the author, unless the caller is a system administrator."""
    thread = make_thread()
    comment_id = add_comment(thread)

    thread.edit_comment(comment_id, AUTHOR, False, "own edit", (), NOW, 10_000, 20)
    with pytest.raises(CommentAuthorMismatchError):
        thread.edit_comment(comment_id, uuid4(), False, "hijack", (), NOW, 10_000, 20)

    thread.edit_comment(comment_id, uuid4(), True, "admin edit", (), NOW, 10_000, 20)
    assert thread.comments[comment_id].body == "admin edit"
    assert thread.comments[comment_id].edited_at == NOW


def test_editing_or_discarding_an_unknown_comment_is_rejected() -> None:
    """Both commands address a live comment only."""
    thread = make_thread()

    with pytest.raises(UnknownCommentError):
        thread.edit_comment(uuid4(), AUTHOR, False, "body", (), NOW, 10_000, 20)
    with pytest.raises(UnknownCommentError):
        thread.discard_comment(uuid4(), NOW)

    comment_id = add_comment(thread)
    thread.discard_comment(comment_id, NOW)
    assert thread.comments[comment_id].discarded_at == NOW
    with pytest.raises(UnknownCommentError):
        thread.edit_comment(comment_id, AUTHOR, False, "body", (), NOW, 10_000, 20)
