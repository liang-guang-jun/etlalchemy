"""Errors raised by the semantic aggregates."""

from __future__ import annotations


class SemanticError(Exception):
    """Base class for every error of the semantic context."""


class UnknownModelError(SemanticError):
    """Raised when a model does not exist."""


class UnknownEntityError(SemanticError):
    """Raised when an entity name is not registered in the model."""


class InvalidEntityNameError(SemanticError):
    """Raised when an entity name is blank or contains a path separator."""


class DuplicateEntityError(SemanticError):
    """Raised when an entity name is already taken."""


class EntityInUseError(SemanticError):
    """Raised when an entity cannot change its table because relationships use it."""


class UnknownRelationshipError(SemanticError):
    """Raised when a relationship id is not registered in the model."""


class DuplicateRelationshipError(SemanticError):
    """Raised when a relationship id is already taken."""


class InvalidRelationshipError(SemanticError):
    """Raised when the field references of a relationship are malformed."""


class UnknownDiagramError(SemanticError):
    """Raised when a diagram name is not registered in the model."""


class DuplicateDiagramError(SemanticError):
    """Raised when a diagram name is already taken."""


class InvalidDiagramError(SemanticError):
    """Raised when a diagram name or an operation on the All diagram is invalid."""


class UnknownNodeError(SemanticError):
    """Raised when a diagram has no node for the given entity."""


class DuplicateNodeError(SemanticError):
    """Raised when a diagram already shows the given entity."""


class DiscardedError(SemanticError, RuntimeError):
    """Raised when a command targets a discarded model."""
