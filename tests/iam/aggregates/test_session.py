"""Tests for the session aggregate."""

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
from etlalchemy.iam.aggregates.errors import (
    IamValidationError,
    SessionExpiredError,
    SessionRevokedError,
)
from etlalchemy.iam.aggregates.session import Session

NOW = datetime(2026, 1, 1, tzinfo=UTC)
LATER = NOW + timedelta(hours=8)


def make_session() -> Session:
    """Returns an active password session that expires at LATER."""
    return Session(
        identity_id=uuid4(),
        user_id=uuid4(),
        expires_at=LATER,
        identity_type="PASSWORD",
        credential_version=0,
        tenant_id=uuid4(),
    )


def replay(events: list[Any]) -> Session:
    """Rebuilds a session by applying the given events in order."""
    aggregate: Any = None
    for event in events:
        aggregate = event.mutate(aggregate)
    assert isinstance(aggregate, Session)
    return aggregate


def test_started_event_records_the_binding() -> None:
    """A new session is active and bound to its identity and user."""
    session = make_session()

    assert session.status == "ACTIVE"
    assert session.expires_at == LATER
    event = session.collect_events()[0]
    assert isinstance(event, Session.Started)
    assert event.credential_version == 0


def test_refresh_extends_the_expiry() -> None:
    """Refreshing slides the expiry forward and records the last use."""
    session = make_session()
    new_expiry = LATER + timedelta(hours=1)
    session.refresh(new_expiry, last_seen_at=NOW)

    assert session.expires_at == new_expiry
    assert replay(session.collect_events()).expires_at == new_expiry


def test_refresh_must_extend_the_expiry() -> None:
    """A refresh that does not extend the expiry is rejected."""
    with pytest.raises(IamValidationError):
        make_session().refresh(LATER, last_seen_at=NOW)


def test_refresh_rejects_revoked_and_expired_sessions() -> None:
    """A revoked or expired session cannot be refreshed."""
    revoked = make_session()
    revoked.revoke("logout")
    with pytest.raises(SessionRevokedError):
        revoked.refresh(LATER + timedelta(hours=1), last_seen_at=NOW)

    expired = make_session()
    with pytest.raises(SessionExpiredError):
        expired.refresh(LATER + timedelta(hours=1), last_seen_at=LATER)


def test_revoke_is_terminal_and_idempotent() -> None:
    """Revoking twice records one transition and keeps the reason."""
    session = make_session()
    session.revoke("logout")
    session.revoke("admin_revoked")

    assert session.status == "REVOKED"
    assert session.revoked_reason == "logout"


def test_deny_records_an_audit_event_without_changing_state() -> None:
    """A denied attempt is recorded but leaves the session untouched."""
    session = make_session()
    version = session.version
    session.deny("doc:readme", "read", reason="outside_scopes")

    event = session.collect_events()[-1]
    assert isinstance(event, Session.AccessDenied)
    assert (event.obj, event.act, event.reason) == ("doc:readme", "read", "outside_scopes")
    assert session.status == "ACTIVE"
    assert session.version == version + 1
