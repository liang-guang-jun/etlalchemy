"""Tests for the shared bearer token authenticator."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from etlalchemy.app.auth.authenticator import SessionAuthenticator
from etlalchemy.app.auth.errors import InvalidTokenError
from etlalchemy.app.auth.session import AuthSession
from etlalchemy.iam.aggregates.errors import (
    AuthenticationError,
    SessionExpiredError,
    SessionRevokedError,
)
from etlalchemy.iam.aggregates.types import Permission
from etlalchemy.iam.application import SessionRef


@dataclass
class FakeIam:
    """Stand-in for ``IamApplication`` with the two methods the authenticator uses."""

    reference: SessionRef | None = None
    error: Exception | None = None
    permissions: frozenset[Permission] = frozenset()

    async def validate_session(self, session_id: UUID) -> SessionRef:
        """Returns the configured reference or raises the configured error."""
        if self.error is not None:
            raise self.error
        assert self.reference is not None
        return self.reference

    async def effective_permissions(self, session_id: UUID) -> frozenset[Permission]:
        """Returns the configured permission set."""
        return self.permissions


def build_reference(*, is_system_admin: bool = False) -> SessionRef:
    """Returns a session reference valid for the next hour."""
    return SessionRef(
        session_id=uuid4(),
        identity_id=uuid4(),
        user_id=uuid4(),
        tenant_id=None,
        expires_at=datetime.now(UTC) + timedelta(hours=1),
        is_system_admin=is_system_admin,
    )


@pytest.mark.parametrize(
    "token",
    [
        "",
        "not-a-token",
        "iam_sess_",
        "iam_sess_not-a-uuid",
        "bearer " + str(uuid4()),
    ],
)
def test_extract_session_id_rejects_malformed_tokens(token: str) -> None:
    """Only ``iam_sess_<uuid>`` tokens carry a session id."""
    authenticator = SessionAuthenticator(FakeIam())  # type: ignore[arg-type]

    with pytest.raises(InvalidTokenError):
        authenticator.extract_session_id(token)


def test_extract_session_id_reads_the_uuid_after_the_prefix() -> None:
    """The prefix is stripped and the rest parsed as a UUID."""
    session_id = uuid4()
    authenticator = SessionAuthenticator(FakeIam())  # type: ignore[arg-type]

    assert authenticator.extract_session_id(f"iam_sess_{session_id}") == session_id


async def test_authenticate_returns_the_session_and_its_permissions() -> None:
    """A valid token resolves to the caller, the tenant and the live permissions."""
    reference = build_reference(is_system_admin=True)
    permission = Permission(resource="*", action="*")
    authenticator = SessionAuthenticator(
        FakeIam(reference=reference, permissions=frozenset({permission})),  # type: ignore[arg-type]
    )

    session = await authenticator.authenticate(f"iam_sess_{reference.session_id}")

    assert session == AuthSession(
        session_id=reference.session_id,
        user_id=reference.user_id,
        identity_id=reference.identity_id,
        tenant_id=reference.tenant_id,
        expires_at=reference.expires_at,
        is_system_admin=True,
        permissions=frozenset({permission}),
    )


@pytest.mark.parametrize(
    "error",
    [
        AuthenticationError("unknown"),
        SessionRevokedError("revoked"),
        SessionExpiredError("expired"),
    ],
)
async def test_authenticate_hides_why_the_session_is_unusable(error: Exception) -> None:
    """Every unusable session becomes the same opaque token error."""
    authenticator = SessionAuthenticator(FakeIam(error=error))  # type: ignore[arg-type]

    with pytest.raises(InvalidTokenError) as raised:
        await authenticator.authenticate(f"iam_sess_{uuid4()}")

    assert str(raised.value) == "invalid or expired token"
