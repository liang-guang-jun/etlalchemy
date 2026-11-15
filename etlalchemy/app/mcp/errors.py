"""Maps catalog domain errors onto MCP error messages.

Every message carries a bracketed category so a model can pick a retry strategy:
`[conflict]` for a rejected write, `[not_found]` for an unknown reference and
`[internal]` for anything else.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from eventsourcing.persistence import RecordConflictError

from etlalchemy.catalog.aggregates.errors import (
    DiscardedError as CatalogDiscardedError,
)
from etlalchemy.catalog.aggregates.errors import (
    DuplicateFieldError,
    DuplicateSchemaError,
    DuplicateTableError,
    InvalidDataTypeError,
    UnknownFieldError,
    UnknownSchemaError,
    UnknownTableError,
)
from etlalchemy.comment.aggregates.errors import (
    CommentError,
    UnknownCommentError,
    UnknownMentionedUserError,
    UnknownTargetError,
    UnknownTargetTypeError,
    UnknownThreadError,
)
from etlalchemy.iam.aggregates.errors import (
    AuthenticationError,
    IamError,
    PermissionDeniedError,
    SessionExpiredError,
    SessionRevokedError,
    UnknownAuthProviderError,
    UnknownGroupError,
    UnknownIdentityError,
    UnknownTenantError,
    UnknownUserError,
)
from etlalchemy.ingestion.aggregates.errors import (
    IngestionError,
    UnknownConnectionError,
    UnknownImportRunError,
)
from etlalchemy.semantic.aggregates.errors import (
    SemanticError,
    UnknownDiagramError,
    UnknownEntityError,
    UnknownModelError,
    UnknownNodeError,
    UnknownRelationshipError,
)
from etlalchemy.vocabulary.aggregates.errors import (
    UnknownAliasError,
    UnknownDomainError,
    UnknownLinkError,
    UnknownParentError,
    UnknownTermError,
    VocabularyError,
)

_CONFLICT = (
    DuplicateSchemaError,
    DuplicateTableError,
    DuplicateFieldError,
    InvalidDataTypeError,
    CatalogDiscardedError,
    IngestionError,
    SemanticError,
    VocabularyError,
    CommentError,
    IamError,
    RecordConflictError,
)
_UNAUTHORIZED = (
    AuthenticationError,
    SessionExpiredError,
    SessionRevokedError,
)
_FORBIDDEN = (PermissionDeniedError,)
_NOT_FOUND = (
    UnknownSchemaError,
    UnknownTableError,
    UnknownFieldError,
    UnknownConnectionError,
    UnknownImportRunError,
    UnknownThreadError,
    UnknownCommentError,
    UnknownTargetTypeError,
    UnknownTargetError,
    UnknownMentionedUserError,
    UnknownModelError,
    UnknownEntityError,
    UnknownRelationshipError,
    UnknownDiagramError,
    UnknownNodeError,
    UnknownDomainError,
    UnknownTermError,
    UnknownParentError,
    UnknownLinkError,
    UnknownAliasError,
    UnknownTenantError,
    UnknownUserError,
    UnknownIdentityError,
    UnknownGroupError,
    UnknownAuthProviderError,
)


def to_mcp_error(exc: Exception) -> str:
    """Returns the MCP error message of a domain exception."""
    if isinstance(exc, _NOT_FOUND):
        return f"[not_found] {exc}"
    if isinstance(exc, _UNAUTHORIZED):
        return f"[unauthorized] {exc}"
    if isinstance(exc, _FORBIDDEN):
        return f"[forbidden] {exc}"
    if isinstance(exc, _CONFLICT):
        return f"[conflict] {exc}"
    return f"[internal] {exc}"


@contextmanager
def mcp_error_guard() -> Iterator[None]:
    """Converts a domain exception into the MCP error convention."""
    try:
        yield
    except Exception as exc:
        raise RuntimeError(to_mcp_error(exc)) from exc
