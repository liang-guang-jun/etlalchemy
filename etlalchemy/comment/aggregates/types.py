"""Value objects shared by the comment aggregates and projections."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID


class ThreadStatus(StrEnum):
    """Lifecycle status of a comment thread."""

    OPEN = "OPEN"
    """The thread accepts comments and can be resolved or discarded."""

    RESOLVED = "RESOLVED"
    """The discussion is settled; writing requires a reopen first."""

    DISCARDED = "DISCARDED"
    """The thread is soft-deleted and rejects every command."""


DEFAULT_TARGET_TYPES: frozenset[str] = frozenset(
    {
        "catalog",
        "schema",
        "table",
        "field",
        "semantic_model",
        "semantic_entity",
        "relationship",
        "domain",
        "term",
        "ingestion_connection",
        "import_run",
        "tenant",
        "user",
        "group",
    },
)
"""Target types declared out of the box.

Every entry is addressable by a UUID: catalog fields and semantic entities carry
their own identity now, so a discussion can hang off them. Diagrams are still
keyed by name inside their model and stay out of the registry; a thread
references its target by ``(target_type, target_id)`` only.
"""


@dataclass(frozen=True, slots=True)
class Comment:
    """One comment of a thread.

    Comments are stored flat in the aggregate; the reply relation is the
    ``parent_comment_id`` link, and the depth is derived from the parent chain.
    """

    comment_id: UUID
    """ID of the comment, unique across every thread."""
    author_user_id: UUID
    """ID of the user who wrote the comment."""
    author_tenant_id: UUID | None
    """Tenant the author acted in, or ``None`` for a tenant-free session."""
    parent_comment_id: UUID | None
    """Comment this one replies to, or ``None`` for the root comment."""
    body: str
    """Plain-text body, already stripped when the event was recorded."""
    mentions: tuple[UUID, ...]
    """Users mentioned by the comment, deduplicated, in first-seen order."""
    created_at: datetime
    """Moment the comment was written."""
    edited_at: datetime | None = None
    """Moment of the last edit, or ``None`` when never edited."""
    discarded_at: datetime | None = None
    """Moment the comment was soft-deleted, or ``None`` while it is live."""
