"""Value objects and enumerations shared by the IAM aggregates.

Events carry primitives only: the value objects below are rebuilt from those
primitives inside the command bodies, so replay works with the default
``JSONTranscoder`` without registering a transcoding per nested dataclass.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import ClassVar, Literal, cast
from urllib.parse import urlparse
from uuid import UUID

from etlalchemy.iam.aggregates.errors import (
    IamValidationError,
    IdentityInvariantError,
    InvalidProviderConfigError,
)

TenantStatus = Literal["ACTIVE", "SUSPENDED"]
"""Lifecycle status of a tenant."""

UserStatus = Literal["ACTIVE", "SUSPENDED"]
"""Lifecycle status of a user."""

IdentityType = Literal["PASSWORD", "OIDC", "API_KEY"]
"""Kind of login method an identity represents."""

IdentityStatus = Literal["ACTIVE", "DISABLED"]
"""Lifecycle status of an identity."""

ApiKeyStatus = Literal["ACTIVE", "GRACE", "REVOKED"]
"""State of one API key: ``ACTIVE`` -> ``GRACE`` -> ``REVOKED``."""

GroupMemberKind = Literal["user", "group"]
"""Kind of member a group holds."""

SessionStatus = Literal["ACTIVE", "REVOKED"]
"""Lifecycle status of a session."""

ProviderKind = Literal["OIDC"]
"""Kind of external identity source; only ``OIDC`` exists in v1."""

ProviderStatus = Literal["ENABLED", "DISABLED"]
"""Lifecycle status of an auth provider."""

AdminGrantSource = Literal["bootstrap", "admin"]
"""Origin of a system administrator grant."""

LOCAL_PROVIDER = "local"
"""Provider name of a local password identity."""

API_KEY_PROVIDER = "api_key"
"""Provider name of an API key identity."""

MAX_NAME_LENGTH = 64
"""Maximum length of a tenant, user, group or provider key."""

PROVIDER_KEY_PATTERN = re.compile(r"^[a-z0-9_-]{1,64}$")
"""Allowed shape of an auth provider key."""


def validate_name(value: str, what: str) -> str:
    """Validates a free-form name and returns it unchanged.

    Args:
        value: The name to validate.
        what: Noun used in the error message, for example ``tenant``.

    Returns:
        The validated name.

    Raises:
        IamValidationError: If the name is blank or longer than
            :data:`MAX_NAME_LENGTH`.
    """
    if not isinstance(value, str) or not value.strip():
        msg = f"{what} name must not be blank"
        raise IamValidationError(msg)
    if len(value) > MAX_NAME_LENGTH:
        msg = f"{what} name must be at most {MAX_NAME_LENGTH} characters"
        raise IamValidationError(msg)
    return value


def validate_provider_key(value: str) -> str:
    """Validates an auth provider key.

    Args:
        value: The provider key to validate.

    Returns:
        The validated provider key.

    Raises:
        IamValidationError: If the key does not match
            :data:`PROVIDER_KEY_PATTERN`.
    """
    if not PROVIDER_KEY_PATTERN.fullmatch(value or ""):
        msg = "provider key must match [a-z0-9_-]{1,64}"
        raise IamValidationError(msg)
    return value


def ensure_tenant_status(value: str) -> TenantStatus:
    """Returns the tenant status, rejecting anything else."""
    if value not in ("ACTIVE", "SUSPENDED"):
        msg = f"unknown tenant status: {value!r}"
        raise IamValidationError(msg)
    return cast(TenantStatus, value)


def ensure_user_status(value: str) -> UserStatus:
    """Returns the user status, rejecting anything else."""
    if value not in ("ACTIVE", "SUSPENDED"):
        msg = f"unknown user status: {value!r}"
        raise IamValidationError(msg)
    return cast(UserStatus, value)


def ensure_identity_status(value: str) -> IdentityStatus:
    """Returns the identity status, rejecting anything else."""
    if value not in ("ACTIVE", "DISABLED"):
        msg = f"unknown identity status: {value!r}"
        raise IamValidationError(msg)
    return cast(IdentityStatus, value)


def ensure_identity_type(value: str) -> IdentityType:
    """Returns the identity type, rejecting anything else."""
    if value not in ("PASSWORD", "OIDC", "API_KEY"):
        msg = f"unknown identity type: {value!r}"
        raise IdentityInvariantError(msg)
    return cast(IdentityType, value)


def ensure_provider_status(value: str) -> ProviderStatus:
    """Returns the provider status, rejecting anything else."""
    if value not in ("ENABLED", "DISABLED"):
        msg = f"unknown provider status: {value!r}"
        raise IamValidationError(msg)
    return cast(ProviderStatus, value)


def ensure_member_status(value: str) -> Literal["ACTIVE", "SUSPENDED"]:
    """Returns the membership status, rejecting anything else."""
    if value not in ("ACTIVE", "SUSPENDED"):
        msg = f"unknown membership status: {value!r}"
        raise IamValidationError(msg)
    return cast(Literal["ACTIVE", "SUSPENDED"], value)


def ensure_member_kind(value: str) -> GroupMemberKind:
    """Returns the group member kind, rejecting anything else."""
    if value not in ("user", "group"):
        msg = f"unknown group member kind: {value!r}"
        raise IamValidationError(msg)
    return cast(GroupMemberKind, value)


@dataclass(frozen=True)
class Permission:
    """A normalised ``resource:action`` pair."""

    resource: str
    """Identifier of the protected resource, for example ``doc``."""
    action: str
    """Action performed on the resource, for example ``read``."""

    @classmethod
    def parse(cls, text: str) -> Permission:
        """Parses ``resource:action`` text into a permission.

        Args:
            text: Text such as ``doc:read`` or ``project:alpha/doc:read``.

        Returns:
            The parsed permission.

        Raises:
            IamValidationError: If the text has no action or a blank/space
                containing segment.
        """
        resource, separator, action = (text or "").rpartition(":")
        if not separator or not resource.strip() or not action.strip():
            msg = f"permission must look like 'resource:action': {text!r}"
            raise IamValidationError(msg)
        if any(character.isspace() for character in f"{resource}{action}"):
            msg = f"permission must not contain whitespace: {text!r}"
            raise IamValidationError(msg)
        return cls(resource=resource, action=action)

    def __str__(self) -> str:
        """Renders the permission as ``resource:action``."""
        return f"{self.resource}:{self.action}"


@dataclass(frozen=True)
class Membership:
    """A user's membership of a tenant, as tracked by the tenant."""

    joined_at: datetime
    """Moment the user joined the tenant."""
    status: Literal["ACTIVE", "SUSPENDED"] = "ACTIVE"
    """Whether the membership currently grants access."""


@dataclass(frozen=True)
class TenantMembership:
    """A tenant the user belongs to, as tracked by the user."""

    joined_at: datetime
    """Moment the user joined the tenant."""


@dataclass(frozen=True)
class IdentityRef:
    """Reference from a user to one of its login identities."""

    identity_type: IdentityType
    """Kind of the referenced identity."""
    provider: str
    """Provider name of the referenced identity."""


@dataclass(frozen=True)
class GroupMember:
    """One member of a group, either a user or a child group."""

    kind: GroupMemberKind
    """Whether the member is a user or a group."""
    added_at: datetime
    """Moment the member was added."""


@dataclass(frozen=True)
class ApiKey:
    """One API key of an ``API_KEY`` identity.

    Only ``secret_hash`` is stored; the plaintext secret exists in the return
    value of the create/rotate use cases and nowhere else.
    """

    key_id: UUID
    prefix: str
    """Plaintext prefix used to look the key up."""
    secret_hash: str
    """Hash of the secret, never the secret itself."""
    scopes: frozenset[str]
    """Upper bound of permissions the key may exercise."""
    created_at: datetime
    """Moment the key was created."""
    expires_at: datetime | None = None
    """Expiry of the key, or ``None`` for no expiry."""
    rotated_from: UUID | None = None
    """Key this one replaced, or ``None`` when created directly."""
    status: ApiKeyStatus = "ACTIVE"
    """Current state of the key."""
    grace_until: datetime | None = None
    """End of the grace period after a rotation, or ``None``."""


@dataclass(frozen=True)
class OidcConfig:
    """Configuration of an OIDC auth provider.

    The client secret itself is never stored: ``client_secret_ref`` points at a
    secret store entry the adapter resolves per authentication.
    """

    issuer: str
    """Issuer URL of the identity provider."""
    authorization_endpoint: str
    """Authorization endpoint URL."""
    token_endpoint: str
    """Token endpoint URL."""
    jwks_uri: str
    """JWKS document URL."""
    client_id: str
    """OAuth client identifier."""
    client_secret_ref: str
    """Reference of the client secret in the secret store."""
    userinfo_endpoint: str | None = None
    """Optional userinfo endpoint URL."""
    scopes: tuple[str, ...] = field(default=("openid", "email", "profile"))
    """Scopes requested during the authorization code flow."""
    redirect_uris: tuple[str, ...] = ()
    """Redirect URIs the host adapter may send; empty means adapter-configured.

    The identity provider registers these values, so keeping them with the
    provider lets two front ends share one IdP without guessing.
    """

    REQUIRED_FIELDS: ClassVar[tuple[str, ...]] = (
        "issuer",
        "authorization_endpoint",
        "token_endpoint",
        "jwks_uri",
        "client_id",
        "client_secret_ref",
    )
    """Fields that must be present for an OIDC provider."""

    def validate(self) -> None:
        """Validates the configuration.

        Raises:
            InvalidProviderConfigError: If a required field is blank or a URL is
                neither ``https`` nor an ``http://localhost`` development URL.
        """
        mapping = self.to_mapping()
        for name in self.REQUIRED_FIELDS:
            if not mapping.get(name, "").strip():
                msg = f"OIDC config requires {name}"
                raise InvalidProviderConfigError(msg)
        for name in (
            "issuer",
            "authorization_endpoint",
            "token_endpoint",
            "jwks_uri",
            "userinfo_endpoint",
        ):
            value = mapping.get(name)
            if value:
                _validate_url(value, name)
        if not self.scopes:
            msg = "OIDC config requires at least one scope"
            raise InvalidProviderConfigError(msg)
        for redirect_uri in self.redirect_uris:
            _validate_url(redirect_uri, "redirect_uris")

    def to_mapping(self) -> dict[str, str]:
        """Renders the configuration as a JSON-safe mapping of strings."""
        return {
            "issuer": self.issuer,
            "authorization_endpoint": self.authorization_endpoint,
            "token_endpoint": self.token_endpoint,
            "jwks_uri": self.jwks_uri,
            "client_id": self.client_id,
            "client_secret_ref": self.client_secret_ref,
            "userinfo_endpoint": self.userinfo_endpoint or "",
            "scopes": " ".join(self.scopes),
            "redirect_uris": " ".join(self.redirect_uris),
        }

    @classmethod
    def from_mapping(cls, mapping: dict[str, str]) -> OidcConfig:
        """Builds and validates a configuration from a JSON-safe mapping.

        Args:
            mapping: Mapping produced by :meth:`to_mapping`, possibly partial for
                a required-field error.

        Returns:
            The validated configuration.
        """
        scopes = tuple(mapping.get("scopes", "").split()) or (
            "openid",
            "email",
            "profile",
        )
        config = cls(
            issuer=mapping.get("issuer", ""),
            authorization_endpoint=mapping.get("authorization_endpoint", ""),
            token_endpoint=mapping.get("token_endpoint", ""),
            jwks_uri=mapping.get("jwks_uri", ""),
            client_id=mapping.get("client_id", ""),
            client_secret_ref=mapping.get("client_secret_ref", ""),
            userinfo_endpoint=mapping.get("userinfo_endpoint") or None,
            scopes=scopes,
            redirect_uris=tuple(mapping.get("redirect_uris", "").split()),
        )
        config.validate()
        return config


def _validate_url(value: str, name: str) -> None:
    """Rejects a URL that is neither ``https`` nor a local ``http`` URL."""
    parsed = urlparse(value)
    if parsed.scheme == "https" and parsed.netloc:
        return
    if parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1"}:
        return
    msg = f"OIDC config field {name} must be an https URL (http only for localhost)"
    raise InvalidProviderConfigError(msg)
