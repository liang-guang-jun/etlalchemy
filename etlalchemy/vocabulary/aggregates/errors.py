"""Errors shared by the vocabulary aggregates."""

from __future__ import annotations


class VocabularyError(Exception):
    """Base class for errors raised by the vocabulary context."""


class DuplicateDomainError(VocabularyError):
    """Raised when a domain name is already in use."""


class UnknownDomainError(VocabularyError):
    """Raised when a domain is not known."""


class DuplicateTermError(VocabularyError):
    """Raised when a term path is already registered in a domain."""


class UnknownTermError(VocabularyError):
    """Raised when a term path is not registered in a domain."""


class DuplicateAliasError(VocabularyError):
    """Raised when a term already carries the given alias."""


class UnknownAliasError(VocabularyError):
    """Raised when a term does not carry the given alias."""


class UnknownLinkError(VocabularyError):
    """Raised when a term link does not exist or its target is unknown."""


class InvalidTermStateError(VocabularyError):
    """Raised when a command is not allowed in the current term status."""


class InvalidLinkError(VocabularyError):
    """Raised when a link target description is structurally invalid."""


class InvalidAliasError(VocabularyError):
    """Raised when an alias is blank."""


class InvalidTermNameError(VocabularyError):
    """Raised when a term name is blank or contains the path separator."""


class InvalidPathError(VocabularyError):
    """Raised when a term path does not match the term name or tree position."""


class InvalidColorError(VocabularyError, ValueError):
    """Raised when a term colour is not a blank or ``#rgb``/``#rrggbb`` hex value."""


class CycleError(VocabularyError):
    """Raised when moving a term under itself or one of its descendants."""


class UnknownParentError(VocabularyError):
    """Raised when a term names a parent that does not exist in the same domain."""


class DiscardedError(VocabularyError, RuntimeError):
    """Raised when a command targets an aggregate that was discarded."""
