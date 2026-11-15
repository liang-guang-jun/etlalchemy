"""Read model and projection of the comment bounded context."""

from etlalchemy.comment.projection.projection import (
    CommentEventApplication,
    CommentProjection,
    run_comment_projection,
)
from etlalchemy.comment.projection.sqlalchemy import SQLAlchemyCommentView
from etlalchemy.comment.projection.view import (
    CommentRow,
    CommentView,
    ThreadRow,
    as_uuid,
)

__all__ = [
    "CommentEventApplication",
    "CommentProjection",
    "CommentRow",
    "CommentView",
    "SQLAlchemyCommentView",
    "ThreadRow",
    "as_uuid",
    "run_comment_projection",
]
