"""Tests for the identity aggregate."""

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest

from etlalchemy.iam.aggregates.errors import (
    DiscardedError,
    DuplicateIdentityError,
    IdentityInvariantError,
)
from etlalchemy.iam.aggregates.identity import Identity

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def replay(events: list[Any]) -> Identity:
    """Rebuilds an identity by applying the given events in order."""
    aggregate: Any = None
    for event in events:
        aggregate = event.mutate(aggregate)
    assert isinstance(aggregate, Identity)
    return aggregate


def password_identity() -> Identity:
    """Returns a password identity of a random user."""
    return Identity(uuid4(), "PASSWORD", "local", "Password")


def test_password_change_stores_the_hash_and_bumps_the_version() -> None:
    """A password change keeps only the hash and increments credential_version."""
    identity = password_identity()
    identity.change_password("$argon2id$hash")

    assert identity.password_hash == "$argon2id$hash"
    assert identity.credential_version == 1
    restored = replay(identity.collect_events())
    assert restored.password_hash == "$argon2id$hash"
    assert restored.credential_version == 1


def test_password_events_never_render_the_hash() -> None:
    """The password event repr redacts the credential material."""
    identity = password_identity()
    identity.change_password("$argon2id$hash")

    event = identity.collect_events()[-1]
    assert "$argon2id$hash" not in repr(event)
    assert "$argon2id$hash" not in repr(identity)


def test_password_commands_require_a_password_identity() -> None:
    """OIDC and API key identities refuse password commands."""
    identity = Identity(uuid4(), "OIDC", "oidc:corp")

    with pytest.raises(IdentityInvariantError):
        identity.change_password("$argon2id$hash")


def test_linking_an_oidc_subject_bumps_the_version() -> None:
    """Binding an issuer and subject updates the state and the credential version."""
    identity = Identity(uuid4(), "OIDC", "oidc:corp")
    provider_id = uuid4()
    identity.link_oidc_subject(provider_id, "https://idp.example", "subject-1")

    assert identity.oidc_subject == "subject-1"
    assert identity.credential_version == 1
    restored = replay(identity.collect_events())
    assert (restored.provider_id, restored.oidc_issuer, restored.oidc_subject) == (
        provider_id,
        "https://idp.example",
        "subject-1",
    )


def test_api_keys_are_created_rotated_and_revoked() -> None:
    """An API key moves through ACTIVE, GRACE and REVOKED and survives replay."""
    identity = Identity(uuid4(), "API_KEY", "api_key")
    old_key, new_key = uuid4(), uuid4()
    identity.add_api_key(
        old_key,
        "iam_ak_abcd",
        "hash-old",
        scopes=("doc:read",),
        created_at=NOW,
    )
    assert identity.api_keys[old_key].scopes == frozenset({"doc:read"})

    grace_until = NOW + timedelta(days=1)
    identity.rotate_api_key(old_key, new_key, "iam_ak_efgh", "hash-new", grace_until)
    assert identity.api_keys[old_key].status == "GRACE"
    assert identity.api_keys[old_key].grace_until == grace_until
    assert identity.api_keys[new_key].rotated_from == old_key
    assert identity.api_keys[new_key].scopes == frozenset({"doc:read"})

    restored = replay(identity.pending_events)
    assert restored.api_keys[old_key].status == "GRACE"
    assert restored.api_keys[new_key].prefix == "iam_ak_efgh"

    identity.revoke_api_key(old_key, NOW)
    assert identity.api_keys[old_key].status == "REVOKED"
    assert replay(identity.pending_events).api_keys[old_key].status == "REVOKED"


def test_rotating_a_key_that_is_not_active_is_rejected() -> None:
    """Only an active key can be rotated."""
    identity = Identity(uuid4(), "API_KEY", "api_key")
    key_id = uuid4()
    identity.add_api_key(key_id, "iam_ak_abcd", "hash", created_at=NOW)
    identity.revoke_api_key(key_id, NOW)

    with pytest.raises(IdentityInvariantError):
        identity.rotate_api_key(key_id, uuid4(), "iam_ak_efgh", "hash", NOW)


def test_duplicate_api_key_is_rejected() -> None:
    """The same key id cannot be added twice."""
    identity = Identity(uuid4(), "API_KEY", "api_key")
    key_id = uuid4()
    identity.add_api_key(key_id, "iam_ak_abcd", "hash", created_at=NOW)

    with pytest.raises(DuplicateIdentityError):
        identity.add_api_key(key_id, "iam_ak_abcd", "hash", created_at=NOW)


def test_discarded_identity_rejects_every_command() -> None:
    """A discarded identity refuses metadata and credential changes."""
    identity = password_identity()
    identity.discard()

    with pytest.raises(DiscardedError):
        identity.change(display_name="x")
    with pytest.raises(DiscardedError):
        identity.change_password("$argon2id$hash")
    with pytest.raises(DiscardedError):
        identity.discard()
