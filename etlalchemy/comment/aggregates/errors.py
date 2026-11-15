"""Errors raised by the comment aggregates and use cases.

Every error subclasses :class:`CommentError` so the delivery layers can map one
base type. A missing reference (thread, comment, target or mentioned user) has
its own error class because the HTTP layer answers it with a different status
than a rule that rejects a well-formed command.
"""


class CommentError(Exception):
    """Base class for errors raised by the comment context."""


class CommentValidationError(CommentError):
    """Raised when a command carries a field that violates a general rule."""


class UnknownThreadError(CommentError):
    """Raised when a thread does not exist or has been discarded."""


class UnknownCommentError(CommentError):
    """Raised when a comment does not exist in the thread or has been discarded."""


class UnknownTargetTypeError(CommentError):
    """Raised when a target type is not declared by the registry."""


class UnknownTargetError(CommentError):
    """Raised when the commented target does not exist."""


class UnknownMentionedUserError(CommentError):
    """Raised when a mentioned user does not exist or is not active."""


class ThreadResolvedError(CommentError):
    """Raised when a command writes to a resolved thread."""


class ThreadDiscardedError(CommentError):
    """Raised when a command targets a discarded thread."""


class InvalidThreadStateError(CommentError):
    """Raised when the thread is not in a state that allows the command."""


class CommentAuthorMismatchError(CommentError):
    """Raised when a user edits a comment written by somebody else."""


class CommentCycleError(CommentError):
    """Raised when a reply would make the parent chain cyclic."""


class CommentBodyEmptyError(CommentError):
    """Raised when a comment body is blank."""


class CommentBodyTooLongError(CommentError):
    """Raised when a comment body exceeds the configured length."""


class MentionsLimitExceededError(CommentError):
    """Raised when a comment mentions more users than the configured limit."""


class InvalidThreadTransitionError(CommentError):
    """Raised when a status transition is not allowed from the current status."""


class ThreadFullError(CommentError):
    """Raised when a thread already holds the maximum number of comments."""


class DuplicateThreadError(CommentError):
    """Raised when a target already has a live thread and only one is allowed."""


class DuplicateCommentError(CommentError):
    """Raised when the given comment id is already used in the thread."""
