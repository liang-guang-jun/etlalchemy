"""Session aggregate: one authenticated login instance.

A session is bound to an identity rather than to a user, so disabling or
re-credentialing one identity only invalidates the sessions it issued.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from eventsourcing.domain import Aggregate, AggregateCreated, event

from etlalchemy.iam.aggregates.errors import (
    IamValidationError,
    SessionExpiredError,
    SessionRevokedError,
)
from etlalchemy.iam.aggregates.types import SessionStatus, ensure_identity_type


class Session(Aggregate):
    """Aggregate root for one login session.

    Expiry produces no event: the read model and the authorization check compare
    ``expires_at`` against the wall clock, so a session that nobody touches does
    not grow its event stream.
    """

    def __init__(
        self,
        identity_id: UUID,
        user_id: UUID,
        expires_at: datetime,
        identity_type: str,
        credential_version: int,
        tenant_id: UUID | None = None,
        api_key_id: UUID | None = None,
    ) -> None:
        """Initialises an active session that expires at the given moment."""
        self.identity_id = identity_id
        self.user_id = user_id
        self.tenant_id = tenant_id
        self.identity_type = ensure_identity_type(identity_type)
        self.api_key_id = api_key_id
        self.credential_version = credential_version
        self.expires_at = expires_at
        self.last_seen_at = expires_at
        self.status: SessionStatus = "ACTIVE"
        self.revoked_reason: str | None = None

    class Event(Aggregate.Event):
        """Base class for events raised by the session aggregate."""

    @dataclass(frozen=True)
    class Started(AggregateCreated):
        """Recorded when a session is issued."""

        identity_id: UUID
        """ID of the identity that authenticated."""
        user_id: UUID
        """ID of the authenticated user."""
        expires_at: datetime
        """Moment the session stops being valid."""
        identity_type: str
        """Kind of the identity that authenticated."""
        credential_version: int
        """Credential version of the identity at authentication time."""
        tenant_id: UUID | None = None
        """Tenant the session acts in, or ``None`` for a global session."""
        api_key_id: UUID | None = None
        """API key that issued the session, or ``None``."""

    @dataclass(frozen=True)
    class Refreshed(Event):
        """Recorded when a session is extended."""

        expires_at: datetime
        """New expiry."""
        last_seen_at: datetime
        """Moment the session was last used."""

    @dataclass(frozen=True)
    class Revoked(Event):
        """Recorded when a session is revoked."""

        reason: str
        """Why the session was revoked."""

    @dataclass(frozen=True)
    class AccessDenied(Event):
        """Recorded when an authorization check fails for this session.

        The event changes no state; it exists so the audit projection can record
        the denied attempt without a separate audit stream.
        """

        obj: str
        """Resource the session tried to access."""
        act: str
        """Action the session tried to perform."""
        reason: str = "denied"
        """Short machine-readable reason."""
        actor_user_id: UUID | None = None
        """User behind the session, when known."""
        actor_identity_id: UUID | None = None
        """Identity behind the session, when known."""

    @event(Refreshed)
    def refresh(self, expires_at: datetime, last_seen_at: datetime) -> None:
        """Extends the session to a new expiry."""
        self._ensure_active(last_seen_at)
        if expires_at <= self.expires_at:
            msg = "refresh must extend the expiry"
            raise IamValidationError(msg)
        self.expires_at = expires_at
        self.last_seen_at = last_seen_at

    @event(Revoked)
    def revoke(self, reason: str) -> None:
        """Revokes the session; revoking twice is a no-op."""
        if self.status == "REVOKED":
            return
        self.status = "REVOKED"
        self.revoked_reason = reason

    @event(AccessDenied)
    def deny(
        self,
        obj: str,
        act: str,
        reason: str = "denied",
        actor_user_id: UUID | None = None,
        actor_identity_id: UUID | None = None,
    ) -> None:
        """Records a denied authorization attempt."""

    def is_expired(self, now: datetime) -> bool:
        """Returns whether the session is past its expiry at ``now``."""
        return now >= self.expires_at

    def _ensure_active(self, now: datetime) -> None:
        """Raises when the session was revoked or has expired."""
        if self.status == "REVOKED":
            msg = "session is revoked"
            raise SessionRevokedError(msg)
        if self.is_expired(now):
            msg = "session is expired"
            raise SessionExpiredError(msg)
