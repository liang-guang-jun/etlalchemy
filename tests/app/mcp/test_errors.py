"""Tests for the MCP error mapping."""

import pytest
from etlalchemy.app.mcp.errors import mcp_error_guard, to_mcp_error
from etlalchemy.catalog.aggregates.errors import (
    DuplicateSchemaError,
    UnknownSchemaError,
)
from etlalchemy.comment.aggregates.errors import (
    CommentBodyEmptyError,
    ThreadFullError,
    UnknownCommentError,
    UnknownTargetTypeError,
    UnknownThreadError,
)
from etlalchemy.iam.aggregates.errors import (
    AuthenticationError,
    PermissionDeniedError,
    SessionExpiredError,
)
from etlalchemy.ingestion.aggregates.errors import (
    DuplicateConnectionError,
    UnknownConnectionError,
    UnknownImportRunError,
    UnknownSourceKindError,
)
from etlalchemy.semantic.aggregates.errors import (
    DuplicateEntityError,
    EntityInUseError,
    InvalidRelationshipError,
    UnknownDiagramError,
    UnknownEntityError,
    UnknownModelError,
    UnknownNodeError,
    UnknownRelationshipError,
)
from etlalchemy.vocabulary.aggregates.errors import (
    CycleError,
    DuplicateTermError,
    InvalidTermNameError,
    InvalidTermStateError,
    UnknownParentError,
    UnknownTermError,
)
from eventsourcing.persistence import IntegrityError


async def test_record_conflict_is_reported_as_a_conflict() -> None:
    """An optimistic concurrency failure is retryable, not an internal error."""
    message = to_mcp_error(
        IntegrityError("duplicate key value violates unique constraint")
    )

    assert message.startswith("[conflict] ")
    assert "duplicate key" in message


@pytest.mark.parametrize(
    ("error", "prefix"),
    [
        (DuplicateSchemaError("sales already exists"), "[conflict]"),
        (UnknownSchemaError("sales does not exist"), "[not_found]"),
        (DuplicateConnectionError("warehouse already exists"), "[conflict]"),
        (UnknownConnectionError("warehouse does not exist"), "[not_found]"),
        (UnknownImportRunError("run does not exist"), "[not_found]"),
        (UnknownSourceKindError("unknown"), "[conflict]"),
        (DuplicateTermError("invoice already exists"), "[conflict]"),
        (InvalidTermStateError("cannot approve"), "[conflict]"),
        (CycleError("cannot move under a descendant"), "[conflict]"),
        (InvalidTermNameError("term name must not contain '/'"), "[conflict]"),
        (UnknownTermError("invoice does not exist"), "[not_found]"),
        (UnknownParentError("parent does not exist"), "[not_found]"),
        (DuplicateEntityError("orders already exists"), "[conflict]"),
        (EntityInUseError("orders is referenced"), "[conflict]"),
        (InvalidRelationshipError("from_refs and to_refs differ"), "[conflict]"),
        (UnknownModelError("model does not exist"), "[not_found]"),
        (UnknownEntityError("entity does not exist"), "[not_found]"),
        (UnknownRelationshipError("relationship does not exist"), "[not_found]"),
        (UnknownDiagramError("diagram does not exist"), "[not_found]"),
        (UnknownNodeError("node does not exist"), "[not_found]"),
        (UnknownThreadError("thread does not exist"), "[not_found]"),
        (UnknownCommentError("comment does not exist"), "[not_found]"),
        (UnknownTargetTypeError("field is not registered"), "[not_found]"),
        (CommentBodyEmptyError("body is blank"), "[conflict]"),
        (ThreadFullError("thread is full"), "[conflict]"),
        (AuthenticationError("invalid credentials"), "[unauthorized]"),
        (SessionExpiredError("session expired"), "[unauthorized]"),
        (PermissionDeniedError("not allowed"), "[forbidden]"),
        (RuntimeError("boom"), "[internal]"),
    ],
)
async def test_error_categories(error: Exception, prefix: str) -> None:
    """Domain errors keep their category and unknown errors stay internal."""
    assert to_mcp_error(error).startswith(f"{prefix} ")


async def test_guard_raises_conflict_for_record_conflicts() -> None:
    """The guard turns a record conflict into a conflict-tagged RuntimeError."""
    with pytest.raises(RuntimeError, match=r"^\[conflict\] "), mcp_error_guard():
        raise IntegrityError("duplicate key value violates unique constraint")
