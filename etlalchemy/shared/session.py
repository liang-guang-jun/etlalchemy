"""The caller behind a validated session, shared by every context that needs one.

The IAM context owns sessions, but three other contexts (comment, conversation
and the LLM provider configuration) have to know *who* is calling. They must not
read the IAM tables, so each one declares a port; the value the port returns is
this dataclass. It lives here because the three contexts had copied it verbatim.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

__all__ = ["SessionUser"]


@dataclass(frozen=True)
class SessionUser:
    """The active session behind a command, with the caller it belongs to."""

    session_id: UUID
    """ID of the validated session."""
    user_id: UUID
    """ID of the user behind the session."""
    tenant_id: UUID | None
    """Tenant the session acts in, or ``None`` for a tenant-free session."""
    is_system_admin: bool
    """Whether the user holds the system administrator flag."""
