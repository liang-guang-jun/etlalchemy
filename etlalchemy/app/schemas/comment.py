"""Response models of the comment context."""

from __future__ import annotations

from datetime import datetime
from typing import Self
from uuid import UUID

from pydantic import BaseModel

from etlalchemy.comment.ports.target_lookup import TargetDescription
from etlalchemy.comment.projection.view import CommentRow, ThreadRow


class ThreadResponse(BaseModel):
    """A comment thread as exposed by the delivery layers."""

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
    author_tenant_id: UUID | None = None
    """Tenant the thread was started in, or ``None``."""
    comment_count: int
    """Number of live comments."""
    last_activity_at: datetime
    """Moment of the last comment, resolution or reopen."""
    created_at: datetime
    """Moment the thread was created."""
    resolved_at: datetime | None = None
    """Moment of the last resolution, or ``None``."""
    resolved_by: UUID | None = None
    """ID of the user who resolved the thread, or ``None``."""

    @classmethod
    def from_row(cls, row: ThreadRow) -> Self:
        """Builds the model from a read model row."""
        return cls(
            thread_id=row.thread_id,
            target_type=row.target_type,
            target_id=row.target_id,
            title=row.title,
            status=row.status,
            author_user_id=row.author_user_id,
            author_tenant_id=row.author_tenant_id,
            comment_count=row.comment_count,
            last_activity_at=row.last_activity_at,
            created_at=row.created_at,
            resolved_at=row.resolved_at,
            resolved_by=row.resolved_by,
        )


class CommentResponse(BaseModel):
    """One comment as exposed by the delivery layers."""

    comment_id: UUID
    """ID of the comment."""
    thread_id: UUID
    """ID of the thread that owns the comment."""
    parent_comment_id: UUID | None = None
    """Comment this one replies to, or ``None`` for a root comment."""
    author_user_id: UUID
    """ID of the user who wrote the comment."""
    author_tenant_id: UUID | None = None
    """Tenant the author acted in, or ``None``."""
    body: str
    """Plain-text body of the comment."""
    mentions: list[UUID]
    """Users mentioned by the comment."""
    created_at: datetime
    """Moment the comment was written."""
    edited_at: datetime | None = None
    """Moment of the last edit, or ``None``."""
    discarded_at: datetime | None = None
    """Moment of the soft delete, or ``None`` while the comment is live."""
    depth: int = 0
    """Parent-chain length; the root comment is 0.

    Capped by ``flatten_after`` when the client asks for a flat presentation.
    """

    @classmethod
    def from_row(cls, row: CommentRow) -> Self:
        """Builds the model from a read model row."""
        return cls(
            comment_id=row.comment_id,
            thread_id=row.thread_id,
            parent_comment_id=row.parent_comment_id,
            author_user_id=row.author_user_id,
            author_tenant_id=row.author_tenant_id,
            body=row.body,
            mentions=row.mentions,
            created_at=row.created_at,
            edited_at=row.edited_at,
            discarded_at=row.discarded_at,
            depth=row.depth,
        )


class ThreadDetailResponse(BaseModel):
    """A thread together with its comments."""

    thread: ThreadResponse
    """The thread metadata."""
    comments: list[CommentResponse]
    """The comments of the thread in creation order."""


class ThreadCreatedResponse(BaseModel):
    """Result of ``POST /comments/threads``."""

    thread_id: UUID
    """ID of the new thread."""
    root_comment_id: UUID
    """ID of the first comment."""


class CommentCreatedResponse(BaseModel):
    """Result of ``POST /comments/threads/{thread_id}/comments``."""

    comment_id: UUID
    """ID of the new comment."""
    depth: int
    """Parent-chain length; the root comment is 0."""
    depth_warning: str | None = None
    """Advisory message when the reply exceeds the soft depth, else ``None``."""


class TargetResponse(BaseModel):
    """What a commented element is called, and the ids that lead to it."""

    target_type: str
    """Type of the target."""
    target_id: UUID
    """ID of the target."""
    name: str
    """Name of the target itself."""
    path: str
    """Readable path, for example ``Customer 360 / crm / contacts``."""
    catalog_id: UUID | None = None
    """Catalog the target belongs to, when it is a catalog object."""
    schema_name: str | None = None
    """Schema the target belongs to, when it is a schema, table or field."""
    table_name: str | None = None
    """Table the target belongs to, when it is a table or field."""
    field_name: str | None = None
    """Field name, for a field target."""
    model_id: UUID | None = None
    """Model the target belongs to, when it is a semantic object."""
    entity_name: str | None = None
    """Entity name, for an entity target."""
    domain_id: UUID | None = None
    """Domain the target belongs to, when it is a vocabulary object."""

    @classmethod
    def from_description(cls, description: TargetDescription) -> Self:
        """Builds the model from a lookup description."""
        return cls(
            target_type=description.target_type,
            target_id=description.target_id,
            name=description.name,
            path=description.path,
            catalog_id=description.catalog_id,
            schema_name=description.schema_name,
            table_name=description.table_name,
            field_name=description.field_name,
            model_id=description.model_id,
            entity_name=description.entity_name,
            domain_id=description.domain_id,
        )


class TargetReference(BaseModel):
    """One target a caller wants described."""

    target_type: str
    """Type of the target."""
    target_id: UUID
    """ID of the target."""


class TargetLookup(BaseModel):
    """Body of ``POST /comments/targets/lookup``."""

    refs: list[TargetReference]
    """Targets to describe; duplicates are ignored."""
