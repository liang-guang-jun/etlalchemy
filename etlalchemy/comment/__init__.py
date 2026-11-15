"""Comment bounded context: discussion threads attached to any addressable element."""

from etlalchemy.comment.aggregates import (
    DEFAULT_TARGET_TYPES,
    Comment,
    CommentError,
    Thread,
    ThreadStatus,
)
from etlalchemy.comment.application import (
    CommentApplication,
    CommentCreated,
    CommentOptions,
    ThreadCreated,
    ThreadDetail,
)

__all__ = [
    "DEFAULT_TARGET_TYPES",
    "Comment",
    "CommentApplication",
    "CommentCreated",
    "CommentError",
    "CommentOptions",
    "Thread",
    "ThreadCreated",
    "ThreadDetail",
    "ThreadStatus",
]
