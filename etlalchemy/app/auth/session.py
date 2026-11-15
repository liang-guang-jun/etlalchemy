"""Value object describing an authenticated caller.

The type lives in the assembly layer because it is the contract between the two
delivery layers (HTTP and MCP) and the IAM context; the context itself only knows
sessions and permissions.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from etlalchemy.iam.aggregates.types import Permission

__all__ = ["AuthSession"]


@dataclass(frozen=True)
class AuthSession:
    """A validated bearer token, resolved to the caller it represents."""

    session_id: UUID
    """Id of the IAM session the token stands for."""
    user_id: UUID
    """Id of the authenticated user."""
    identity_id: UUID
    """Id of the identity (password, OIDC or API key) that issued the session."""
    tenant_id: UUID | None
    """Tenant the session acts in, or ``None`` for a global session."""
    expires_at: datetime
    """Moment the session expires; the token becomes invalid with it."""
    is_system_admin: bool
    """Whether the user carries the system administrator flag."""
    permissions: frozenset[Permission]
    """Permissions the session exercises right now, recomputed per request."""
