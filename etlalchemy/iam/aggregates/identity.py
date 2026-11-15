"""Identity aggregate: one login method of a user and its credentials."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

from eventsourcing.domain import Aggregate, AggregateCreated, event

from etlalchemy.iam.aggregates.errors import (
    DiscardedError,
    DuplicateIdentityError,
    IdentityInvariantError,
)
from etlalchemy.iam.aggregates.types import (
    API_KEY_PROVIDER,
    ApiKey,
    IdentityStatus,
    IdentityType,
    ensure_identity_status,
    ensure_identity_type,
)


class Identity(Aggregate):
    """Aggregate root for one login method of a user.

    The aggregate carries the credential material of its type, never the
    plaintext: password identities store an ``Argon2id`` hash, OIDC identities
    store issuer/subject, and API key identities store one hash per key. Every
    credential change increments ``credential_version``, which lets an
    authorization check reject sessions the projection has not revoked yet.
    """

    def __init__(
        self,
        user_id: UUID,
        identity_type: str,
        provider: str,
        display_name: str = "",
        provider_id: UUID | None = None,
        oidc_issuer: str | None = None,
        oidc_subject: str | None = None,
    ) -> None:
        """Initialises an active identity without any credential set yet."""
        self.user_id = user_id
        self.identity_type = ensure_identity_type(identity_type)
        self.provider = provider
        self.display_name = display_name
        self.status: IdentityStatus = "ACTIVE"
        self.credential_version = 0
        self.password_hash: str | None = None
        self.provider_id = provider_id
        self.oidc_issuer = oidc_issuer
        self.oidc_subject = oidc_subject
        self.api_keys: dict[UUID, ApiKey] = {}
        self._is_discarded = False

    class Event(Aggregate.Event):
        """Base class for events raised by the identity aggregate."""

    @dataclass(frozen=True)
    class Started(AggregateCreated):
        """Recorded when an identity is created."""

        user_id: UUID
        """ID of the user that owns the identity."""
        identity_type: str
        """Kind of login method."""
        provider: str
        """Provider name, for example ``local``."""
        display_name: str = ""
        """Human readable name of the identity."""
        provider_id: UUID | None = None
        """Auth provider of an OIDC identity."""
        oidc_issuer: str | None = None
        """Issuer of an OIDC identity, copied from its provider."""
        oidc_subject: str | None = None
        """Subject of an OIDC identity at the provider."""

    @dataclass(frozen=True)
    class Changed(Event):
        """Recorded when identity metadata or status changes."""

        display_name: str | None = None
        """New display name, or ``None`` when unchanged."""
        status: str | None = None
        """New status, or ``None`` when unchanged."""

    @dataclass(frozen=True)
    class PasswordChanged(Event):
        """Recorded when the password hash of a password identity changes."""

        password_hash: str = field(repr=False)
        """New Argon2id hash; plaintext passwords never reach an event."""

    @dataclass(frozen=True)
    class OidcSubjectLinked(Event):
        """Recorded when an OIDC identity is bound to an issuer and subject."""

        provider_id: UUID
        """Auth provider the identity is bound to."""
        issuer: str
        """Issuer the subject belongs to."""
        subject: str
        """Subject identifier at the issuer."""

    @dataclass(frozen=True)
    class ApiKeyCreated(Event):
        """Recorded when an API key is added to an API key identity."""

        key_id: UUID
        """ID of the new key."""
        prefix: str
        """Plaintext prefix used to look the key up."""
        secret_hash: str = field(repr=False)
        """Hash of the key secret."""
        scopes: tuple[str, ...]
        """Upper bound of permissions the key may exercise."""
        created_at: datetime
        """Moment the key was created."""
        expires_at: datetime | None = None
        """Expiry of the key, or ``None`` for no expiry."""
        rotated_from: UUID | None = None
        """Key this one replaced, or ``None`` when created directly."""

    @dataclass(frozen=True)
    class ApiKeyRotated(Event):
        """Recorded when an API key is replaced and the old one enters grace."""

        old_key_id: UUID
        """ID of the key that enters the grace period."""
        new_key_id: UUID
        """ID of the replacement key."""
        new_prefix: str
        """Plaintext prefix of the replacement key."""
        new_secret_hash: str = field(repr=False)
        """Hash of the replacement key secret."""
        grace_until: datetime
        """Moment the old key stops authenticating."""
        created_at: datetime | None = None
        """Moment the replacement key was created."""

    @dataclass(frozen=True)
    class ApiKeyRevoked(Event):
        """Recorded when an API key is revoked."""

        key_id: UUID
        """ID of the revoked key."""
        revoked_at: datetime
        """Moment the key was revoked."""

    @dataclass(frozen=True)
    class Discarded(Event):
        """Recorded when the identity is discarded."""

    @event(Changed)
    def change(self, display_name: str | None = None, status: str | None = None) -> None:
        """Changes the display name and/or status of the identity."""
        self._ensure_not_discarded()
        if display_name is None and status is None:
            msg = "change() requires at least one field"
            raise ValueError(msg)
        checked = None if status is None else ensure_identity_status(status)
        if display_name is not None:
            self.display_name = display_name
        if checked is not None:
            self.status = checked

    @event(PasswordChanged)
    def change_password(self, password_hash: str) -> None:
        """Replaces the password hash and invalidates older sessions."""
        self._ensure_not_discarded()
        self._require_type("PASSWORD")
        if not password_hash.strip():
            msg = "password hash must not be blank"
            raise IdentityInvariantError(msg)
        self.password_hash = password_hash
        self.credential_version += 1

    @event(OidcSubjectLinked)
    def link_oidc_subject(self, provider_id: UUID, issuer: str, subject: str) -> None:
        """Binds the identity to an OIDC provider, issuer and subject."""
        self._ensure_not_discarded()
        self._require_type("OIDC")
        if not issuer.strip() or not subject.strip():
            msg = "OIDC issuer and subject must not be blank"
            raise IdentityInvariantError(msg)
        self.provider_id = provider_id
        self.oidc_issuer = issuer
        self.oidc_subject = subject
        self.credential_version += 1

    @event(ApiKeyCreated)
    def add_api_key(
        self,
        key_id: UUID,
        prefix: str,
        secret_hash: str,
        scopes: tuple[str, ...] = (),
        created_at: datetime | None = None,
        expires_at: datetime | None = None,
        rotated_from: UUID | None = None,
    ) -> None:
        """Adds an API key to an API key identity."""
        self._ensure_not_discarded()
        self._require_type("API_KEY")
        if key_id in self.api_keys:
            msg = f"API key {key_id} already exists"
            raise DuplicateIdentityError(msg)
        self.api_keys[key_id] = ApiKey(
            key_id=key_id,
            prefix=prefix,
            secret_hash=secret_hash,
            scopes=frozenset(scopes),
            created_at=created_at or self.created_on,
            expires_at=expires_at,
            rotated_from=rotated_from,
        )

    @event(ApiKeyRotated)
    def rotate_api_key(
        self,
        old_key_id: UUID,
        new_key_id: UUID,
        new_prefix: str,
        new_secret_hash: str,
        grace_until: datetime,
        created_at: datetime | None = None,
    ) -> None:
        """Replaces an active API key and moves the old one into grace."""
        self._ensure_not_discarded()
        self._require_type("API_KEY")
        old_key = self.api_keys.get(old_key_id)
        if old_key is None:
            msg = f"API key {old_key_id} does not exist"
            raise IdentityInvariantError(msg)
        if old_key.status != "ACTIVE":
            msg = f"API key {old_key_id} is not active"
            raise IdentityInvariantError(msg)
        if new_key_id in self.api_keys:
            msg = f"API key {new_key_id} already exists"
            raise DuplicateIdentityError(msg)
        moment = created_at or self.created_on
        self.api_keys[old_key_id] = ApiKey(
            key_id=old_key.key_id,
            prefix=old_key.prefix,
            secret_hash=old_key.secret_hash,
            scopes=old_key.scopes,
            created_at=old_key.created_at,
            expires_at=old_key.expires_at,
            rotated_from=old_key.rotated_from,
            status="GRACE",
            grace_until=grace_until,
        )
        self.api_keys[new_key_id] = ApiKey(
            key_id=new_key_id,
            prefix=new_prefix,
            secret_hash=new_secret_hash,
            scopes=old_key.scopes,
            created_at=moment,
            expires_at=old_key.expires_at,
            rotated_from=old_key_id,
        )

    @event(ApiKeyRevoked)
    def revoke_api_key(self, key_id: UUID, revoked_at: datetime) -> None:
        """Revokes an API key."""
        self._ensure_not_discarded()
        self._require_type("API_KEY")
        key = self.api_keys.get(key_id)
        if key is None:
            msg = f"API key {key_id} does not exist"
            raise IdentityInvariantError(msg)
        self.api_keys[key_id] = ApiKey(
            key_id=key.key_id,
            prefix=key.prefix,
            secret_hash=key.secret_hash,
            scopes=key.scopes,
            created_at=key.created_at,
            expires_at=key.expires_at,
            rotated_from=key.rotated_from,
            status="REVOKED",
            grace_until=key.grace_until,
        )

    @event(Discarded)
    def discard(self) -> None:
        """Marks the identity as discarded."""
        self._ensure_not_discarded()
        self._is_discarded = True

    @property
    def is_api_key_identity(self) -> bool:
        """Returns whether this identity is the API key container of a user."""
        return self.identity_type == "API_KEY" and self.provider == API_KEY_PROVIDER

    def _require_type(self, expected: IdentityType) -> None:
        """Raises when the identity is not of the expected type."""
        if self.identity_type != expected:
            msg = f"identity {self.id} is {self.identity_type}, not {expected}"
            raise IdentityInvariantError(msg)

    def _ensure_not_discarded(self) -> None:
        """Raises DiscardedError when the identity has been discarded."""
        if self._is_discarded:
            msg = "identity is discarded"
            raise DiscardedError(msg)

    def __repr__(self) -> str:
        """Renders the identity without leaking credential material."""
        return (
            f"Identity(id={self.id}, user_id={self.user_id}, "
            f"identity_type={self.identity_type!r}, provider={self.provider!r}, "
            f"status={self.status!r}, credential_version={self.credential_version}, "
            f"password_hash=<redacted>, oidc_subject={self.oidc_subject!r}, "
            f"api_keys={sorted(str(key) for key in self.api_keys)})"
        )
