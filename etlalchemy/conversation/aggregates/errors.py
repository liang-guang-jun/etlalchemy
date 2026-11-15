"""Errors raised by the conversation aggregate."""

from __future__ import annotations


class ConversationError(Exception):
    """Base class of every error of the conversation context."""


class DiscardedError(ConversationError, RuntimeError):
    """Raised when a command targets a discarded conversation."""


class ConversationFullError(ConversationError):
    """Raised when a conversation already holds the maximum number of messages."""


class DuplicateMessageError(ConversationError):
    """Raised when a message id is used twice in one conversation."""


class DuplicateRunError(ConversationError):
    """Raised when a run id is used twice in one conversation."""


class MessageTooLongError(ConversationError, ValueError):
    """Raised when a message body exceeds the configured limit."""


class MessageEmptyError(ConversationError, ValueError):
    """Raised when a message body is blank."""


class InvalidRunTransitionError(ConversationError):
    """Raised when a run is moved to a status it cannot reach."""


class UnknownMessageError(ConversationError):
    """Raised when a message id does not resolve to a message."""


class UnknownRunError(ConversationError):
    """Raised when a run id does not resolve to a run."""


class UnknownApprovalError(ConversationError):
    """Raised when an approval id does not resolve to an approval."""


class ApprovalAlreadyDecidedError(ConversationError):
    """Raised when an approval is decided twice."""


class UnknownConversationError(ConversationError):
    """Raised when a conversation id does not resolve to a live conversation."""


class RunInProgressError(ConversationError):
    """Raised when a new message arrives while a run is still in flight."""
