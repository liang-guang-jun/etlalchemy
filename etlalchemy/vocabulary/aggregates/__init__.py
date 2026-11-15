"""Aggregates of the vocabulary bounded context."""

from etlalchemy.vocabulary.aggregates.domain import Domain
from etlalchemy.vocabulary.aggregates.errors import (
    CycleError,
    DiscardedError,
    DuplicateAliasError,
    DuplicateDomainError,
    DuplicateTermError,
    InvalidAliasError,
    InvalidLinkError,
    InvalidPathError,
    InvalidTermNameError,
    InvalidTermStateError,
    UnknownAliasError,
    UnknownDomainError,
    UnknownLinkError,
    UnknownParentError,
    UnknownTermError,
    VocabularyError,
)
from etlalchemy.vocabulary.aggregates.term import Term
from etlalchemy.vocabulary.aggregates.types import TARGET_KINDS, TermLink, TermStatus

__all__ = [
    "TARGET_KINDS",
    "CycleError",
    "DiscardedError",
    "Domain",
    "DuplicateAliasError",
    "DuplicateDomainError",
    "DuplicateTermError",
    "InvalidAliasError",
    "InvalidLinkError",
    "InvalidPathError",
    "InvalidTermNameError",
    "InvalidTermStateError",
    "Term",
    "TermLink",
    "TermStatus",
    "UnknownAliasError",
    "UnknownDomainError",
    "UnknownLinkError",
    "UnknownParentError",
    "UnknownTermError",
    "VocabularyError",
]
