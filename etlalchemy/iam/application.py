"""Application service of the IAM context.

Every use case resolves the caller's session through the read model, then loads the
aggregates it needs and saves them in one unit of work. Authentication and
authorization are the only anonymous entry points; everything else takes a
``session_id``.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

import structlog
from eventsourcing.utils import EnvType

from etlalchemy._vendor.eventsourcing.asyncio.application import AsyncApplication
from etlalchemy.iam.adapters.passwords import PasswordHasher
from etlalchemy.iam.aggregates.auth_provider import AuthProvider
from etlalchemy.iam.aggregates.errors import (
    AuthenticationError,
    BootstrapAlreadyCompletedError,
    CredentialError,
    DuplicateAuthProviderError,
    DuplicateEmailError,
    DuplicateGroupError,
    DuplicateIdentityError,
    DuplicateMembershipError,
    DuplicateOidcBindingError,
    DuplicatePermissionGrantError,
    DuplicateTenantError,
    DuplicateUserError,
    GroupCycleError,
    GroupDepthExceededError,
    IamValidationError,
    IdentityInvariantError,
    IdentityUnavailableError,
    LastLoginIdentityError,
    LastSystemAdminError,
    PermissionDeniedError,
    ProviderInUseError,
    ScopeExceedsGrantError,
    SessionExpiredError,
    SessionRevokedError,
    TenantSuspendedError,
    UnknownAuthProviderError,
    UnknownGroupError,
    UnknownIdentityError,
    UnknownMembershipError,
    UnknownTenantError,
    UnknownUserError,
    UserSuspendedError,
)
from etlalchemy.iam.aggregates.group import Group
from etlalchemy.iam.aggregates.identity import Identity
from etlalchemy.iam.aggregates.session import Session
from etlalchemy.iam.aggregates.tenant import Tenant
from etlalchemy.iam.aggregates.types import (
    API_KEY_PROVIDER,
    LOCAL_PROVIDER,
    GroupMemberKind,
    OidcConfig,
    Permission,
)
from etlalchemy.iam.aggregates.user import User
from etlalchemy.iam.projection.view import (
    ApiKeyRow,
    AuditRow,
    GroupMemberRow,
    GroupRow,
    IamView,
    IdentityRow,
    ProviderRow,
    SessionRow,
    TenantRow,
    UserRow,
)
from etlalchemy.shared.logging import get_logger

if TYPE_CHECKING:  # pragma: no cover
    from etlalchemy.iam.aggregates.types import ApiKey
    from etlalchemy.iam.authorization import CasbinAuthorizer
    from etlalchemy.iam.ports.secrets import SecretsResolver

API_KEY_PREFIX_LENGTH = 19
"""Number of leading characters of an API key secret that identify the key."""

DENIED_REASONS = ("credential_changed", "session_inactive")
"""Reasons for which ``authorize`` also revokes the session."""


def _as_utc(value: datetime) -> datetime:
    """Returns a timestamp in UTC, reading a naive value as UTC.

    SQLite has no timezone type, so the datetimes it returns are naive even for
    ``DateTime(timezone=True)`` columns; PostgreSQL returns aware values.
    """
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


@dataclass(frozen=True)
class IamOptions:
    """Runtime knobs of the IAM application that are not domain rules."""

    password_min_length: int = 8
    """Minimum length of a new password."""
    max_api_keys: int = 20
    """Maximum number of live API keys per user."""
    api_key_grace_max_days: int = 30
    """Upper bound of an API key grace period."""
    max_group_depth: int = 64
    """Maximum length of a group ancestor chain."""
    password_session_minutes: int = 480
    """Session lifetime after a password login."""
    oidc_session_minutes: int = 480
    """Session lifetime after an OIDC login."""
    api_key_session_minutes: int = 60
    """Session lifetime after an API key login."""
    api_key_pepper: str | None = None
    """Pepper of the API key hashes; ``None`` keeps a plain SHA-256 digest."""
    record_denied_authorizations: bool = True
    """Whether a denied ``authorize`` call is recorded in the audit log."""


@dataclass(frozen=True)
class SessionRef:
    """Reference to a freshly issued or refreshed session.

    ``is_system_admin`` is only populated by :meth:`IamApplication.validate_session`,
    which is the authentication entry point of the delivery layers; the login use
    cases leave it ``False`` so their responses stay unchanged.
    """

    session_id: UUID
    identity_id: UUID
    user_id: UUID
    tenant_id: UUID | None
    expires_at: datetime
    is_system_admin: bool = False


@dataclass(frozen=True)
class ApiKeySecret:
    """A new API key; the plaintext secret is returned only once."""

    key_id: UUID
    secret: str


@dataclass(frozen=True)
class UnboundOidcIdentity:
    """Signal that an OIDC subject is not bound to any identity yet."""

    issuer: str
    subject: str


class IamApplication(AsyncApplication[UUID]):
    """Application service for the IAM context."""

    name = "iam_application"
    """Application name; the eventsourcing factories derive table names from it."""

    def __init__(
        self,
        view: IamView,
        hasher: PasswordHasher,
        secrets_resolver: SecretsResolver,
        authorizer: CasbinAuthorizer,
        options: IamOptions | None = None,
        env: EnvType | None = None,
    ) -> None:
        """Creates the application and its structured logger."""
        super().__init__(env=env)
        self._view = view
        self._hasher = hasher
        self._secrets = secrets_resolver
        self._authorizer = authorizer
        self._options = options or IamOptions()
        self._log: structlog.stdlib.BoundLogger = get_logger("iam.application")

    # -- bootstrap and system administrators --------------------------------

    async def bootstrap_status(self) -> bool:
        """Returns whether the system already has a live system administrator."""
        return await self._view.count_system_admins() > 0

    async def bootstrap_admin(self, email: str, plain_password: str) -> UUID:
        """Creates the first system administrator of an empty system.

        Args:
            email: Email address, also used as username and display name.
            plain_password: Plaintext password, hashed before it reaches an event.

        Returns:
            The id of the created user.

        Raises:
            BootstrapAlreadyCompletedError: If a system administrator exists.
        """
        self._log.info("iam.bootstrap.start", email=email)
        if await self.bootstrap_status():
            msg = "the system already has a system administrator"
            raise BootstrapAlreadyCompletedError(msg)
        self._validate_password(plain_password)
        normalized = self._normalize_email(email)
        user = User(username=normalized, email=normalized, display_name=normalized)
        identity = Identity(
            user_id=user.id,
            identity_type="PASSWORD",
            provider=LOCAL_PROVIDER,
            display_name="Password",
        )
        user.attach_identity(identity.id, "PASSWORD", LOCAL_PROVIDER)
        identity.change_password(self._hash_password(plain_password))
        user.grant_system_admin("bootstrap")
        await self.save(user, identity)
        self._log.info("iam.bootstrap.done", user_id=str(user.id))
        return user.id

    async def grant_system_admin(self, session_id: UUID, user_id: UUID) -> None:
        """Grants the system administrator flag to another user."""
        self._log.info("iam.system_admin.grant start", user_id=str(user_id))
        await self._require_system_admin(session_id)
        user = await self._user(user_id)
        if not user.password_identity_ids():
            msg = "the user needs a PASSWORD identity to become a system administrator"
            raise IdentityInvariantError(msg)
        user.grant_system_admin("admin")
        await self.save(user)
        self._log.info("iam.system_admin.grant done", user_id=str(user_id))

    async def revoke_system_admin(self, session_id: UUID, user_id: UUID) -> None:
        """Removes the system administrator flag from another user."""
        self._log.info("iam.system_admin.revoke start", user_id=str(user_id))
        await self._require_system_admin(session_id)
        user = await self._user(user_id)
        if user.is_system_admin and await self._view.count_system_admins() <= 1:
            msg = "the last system administrator cannot be revoked"
            raise LastSystemAdminError(msg)
        user.revoke_system_admin()
        await self.save(user)
        self._log.info("iam.system_admin.revoke done", user_id=str(user_id))

    async def list_system_admins(self) -> list[UserRow]:
        """Returns the live system administrators."""
        return await self._view.list_system_admins()

    # -- tenants ------------------------------------------------------------

    async def create_tenant(
        self,
        session_id: UUID,
        name: str,
        description: str = "",
    ) -> UUID:
        """Creates a tenant and returns its id."""
        self._log.info("iam.tenant.create start", name=name)
        await self._require_system_admin(session_id)
        if await self._view.find_tenant_by_name(name) is not None:
            msg = f"tenant {name!r} already exists"
            raise DuplicateTenantError(msg)
        tenant = Tenant(name=name, description=description)
        await self.save(tenant)
        self._log.info("iam.tenant.create done", tenant_id=str(tenant.id))
        return tenant.id

    async def change_tenant(
        self,
        session_id: UUID,
        tenant_id: UUID,
        name: str | None = None,
        description: str | None = None,
        status: str | None = None,
    ) -> None:
        """Changes the name, description or status of a tenant."""
        await self._require_system_admin(session_id)
        if name is not None and await self._view.find_tenant_by_name(name) is not None:
            msg = f"tenant {name!r} already exists"
            raise DuplicateTenantError(msg)
        tenant = await self._tenant(tenant_id)
        tenant.change(name, description, status)
        await self.save(tenant)

    async def discard_tenant(self, session_id: UUID, tenant_id: UUID) -> None:
        """Soft-deletes a tenant and cascades through the projection."""
        self._log.info("iam.tenant.discard start", tenant_id=str(tenant_id))
        await self._require_system_admin(session_id)
        tenant = await self._tenant(tenant_id)
        tenant.discard()
        await self.save(tenant)
        self._log.info("iam.tenant.discard done", tenant_id=str(tenant_id))

    async def add_tenant_member(
        self,
        session_id: UUID,
        tenant_id: UUID,
        user_id: UUID,
    ) -> None:
        """Adds a user to a tenant on both sides of the membership."""
        self._log.info("iam.tenant.member.add start", tenant_id=str(tenant_id))
        await self._require_system_admin(session_id)
        tenant = await self._tenant(tenant_id)
        user = await self._user(user_id)
        if tenant.has_member(user_id):
            msg = f"user {user_id} is already a member of tenant {tenant_id}"
            raise DuplicateMembershipError(msg)
        joined_at = datetime.now(UTC)
        tenant.add_member(user_id, joined_at=joined_at)
        user.join_tenant(tenant_id, joined_at=joined_at)
        await self.save(tenant, user)
        self._log.info("iam.tenant.member.add done", tenant_id=str(tenant_id))

    async def remove_tenant_member(
        self,
        session_id: UUID,
        tenant_id: UUID,
        user_id: UUID,
    ) -> None:
        """Removes a user from a tenant on both sides of the membership."""
        self._log.info("iam.tenant.member.remove start", tenant_id=str(tenant_id))
        await self._require_system_admin(session_id)
        tenant = await self._tenant(tenant_id)
        user = await self._user(user_id)
        if not tenant.has_member(user_id):
            msg = f"user {user_id} is not a member of tenant {tenant_id}"
            raise UnknownMembershipError(msg)
        tenant.remove_member(user_id)
        user.leave_tenant(tenant_id)
        await self.save(tenant, user)
        self._log.info("iam.tenant.member.remove done", tenant_id=str(tenant_id))

    async def list_tenants(self) -> list[TenantRow]:
        """Returns every live tenant."""
        return await self._view.list_tenants()

    async def list_tenant_members(self, session_id: UUID, tenant_id: UUID) -> list[UserRow]:
        """Returns the users that are members of a tenant."""
        await self._require_session(session_id)
        rows = await self._view.list_members(tenant_id)
        return [
            UserRow(
                user_id=row.user_id,
                username=row.username,
                email=row.email,
                display_name="",
                status=row.status,
                is_system_admin=False,
            )
            for row in rows
        ]

    # -- users --------------------------------------------------------------

    async def create_user(
        self,
        session_id: UUID,
        username: str,
        email: str,
        display_name: str = "",
    ) -> UUID:
        """Creates a user without any identity."""
        self._log.info("iam.user.create start", username=username)
        await self._require_system_admin(session_id)
        normalized_username = username.strip().lower()
        normalized_email = self._normalize_email(email)
        await self._ensure_unique_user(normalized_username, normalized_email)
        user = User(
            username=normalized_username,
            email=normalized_email,
            display_name=display_name,
        )
        await self.save(user)
        self._log.info("iam.user.create done", user_id=str(user.id))
        return user.id

    async def change_user(
        self,
        session_id: UUID,
        user_id: UUID,
        username: str | None = None,
        email: str | None = None,
        display_name: str | None = None,
        status: str | None = None,
    ) -> None:
        """Changes the username, email, display name or status of a user."""
        await self._require_system_admin(session_id)
        user = await self._user(user_id)
        if username is not None or email is not None:
            await self._ensure_unique_user(
                None if username is None else username.strip().lower(),
                None if email is None else self._normalize_email(email),
            )
        user.change(
            None if username is None else username.strip().lower(),
            None if email is None else self._normalize_email(email),
            display_name,
            status,
        )
        await self.save(user)

    async def discard_user(self, session_id: UUID, user_id: UUID) -> None:
        """Soft-deletes a user and cascades through the projection."""
        self._log.info("iam.user.discard start", user_id=str(user_id))
        caller = await self._require_system_admin(session_id)
        user = await self._user(user_id)
        if user.is_system_admin and await self._view.count_system_admins() <= 1:
            msg = "the last system administrator cannot be discarded"
            raise LastSystemAdminError(msg)
        user.discard()
        await self.save(user)
        self._log.info("iam.user.discard done", user_id=str(user_id), caller=str(caller.user_id))

    async def list_users(self, session_id: UUID) -> list[UserRow]:
        """Returns every live user."""
        await self._require_system_admin(session_id)
        return await self._view.list_users()

    async def search_users(self, session_id: UUID, term: str, limit: int = 8) -> list[UserRow]:
        """Returns the users whose name, username or email matches a mention."""
        await self._require_session(session_id)
        return await self._view.search_users(term, limit)

    async def get_user(self, session_id: UUID, user_id: UUID) -> UserRow:
        """Returns one user."""
        await self._require_session(session_id)
        row = await self._view.get_user(user_id)
        if row is None:
            msg = f"user {user_id} does not exist"
            raise UnknownUserError(msg)
        return row

    # -- identities ---------------------------------------------------------

    async def create_password_identity(
        self,
        session_id: UUID,
        user_id: UUID,
        plain_password: str,
    ) -> UUID:
        """Creates the password identity of a user and returns its id."""
        self._log.info("iam.identity.password.start", user_id=str(user_id))
        caller = await self._require_self_or_admin(session_id, user_id)
        self._validate_password(plain_password)
        user = await self._user(user_id)
        if user.password_identity_ids():
            msg = f"user {user_id} already has a password identity"
            raise DuplicateIdentityError(msg)
        identity = Identity(
            user_id=user.id,
            identity_type="PASSWORD",
            provider=LOCAL_PROVIDER,
            display_name="Password",
        )
        identity.change_password(self._hash_password(plain_password))
        user.attach_identity(identity.id, "PASSWORD", LOCAL_PROVIDER)
        await self.save(user, identity)
        self._log.info(
            "iam.identity.password.done",
            identity_id=str(identity.id),
            caller=str(caller.user_id),
        )
        return identity.id

    async def create_oidc_identity(
        self,
        session_id: UUID,
        user_id: UUID,
        provider_id: UUID,
        oidc_subject: str,
    ) -> UUID:
        """Creates an OIDC identity bound to a provider and subject.

        This is the pre-binding path: the caller already knows the IdP subject.
        Binding is not idempotent under concurrency - the ``(issuer, subject)``
        lookup reads the projection, so two simultaneous bindings can both pass
        it; the partial unique index in ``iam_oidc_creds`` then rejects the second
        one and the projection retries it forever. A discarded provider is
        rejected, and a tenant-scoped provider requires the user to be a member of
        that tenant.
        """
        self._log.info("iam.identity.oidc.start", user_id=str(user_id))
        await self._require_self_or_admin(session_id, user_id)
        provider = await self._provider_row(provider_id)
        if provider.status != "ENABLED":
            msg = f"auth provider {provider.provider_key!r} is disabled"
            raise IdentityUnavailableError(msg)
        if provider.tenant_id is not None:
            tenant = await self._tenant(provider.tenant_id)
            if not tenant.has_member(user_id):
                msg = (
                    f"auth provider {provider.provider_key!r} serves tenant "
                    f"{provider.tenant_id} only"
                )
                raise UnknownMembershipError(msg)
        issuer = provider.config.get("issuer", "")
        existing = await self._view.find_oidc_identity(issuer, oidc_subject)
        if existing is not None:
            msg = f"subject {oidc_subject!r} is already bound to another identity"
            raise DuplicateOidcBindingError(msg)
        user = await self._user(user_id)
        identity = Identity(
            user_id=user.id,
            identity_type="OIDC",
            provider=f"oidc:{provider.provider_key}",
            display_name=provider.display_name,
        )
        identity.link_oidc_subject(provider_id, issuer, oidc_subject)
        user.attach_identity(identity.id, "OIDC", identity.provider)
        await self.save(user, identity)
        self._log.info("iam.identity.oidc.done", identity_id=str(identity.id))
        return identity.id

    async def change_identity(
        self,
        session_id: UUID,
        identity_id: UUID,
        display_name: str | None = None,
        status: str | None = None,
    ) -> None:
        """Changes the display name or status of an identity."""
        row = await self._identity_row(identity_id)
        await self._require_self_or_admin(session_id, row.user_id)
        identity = await self._identity_aggregate(identity_id)
        identity.change(display_name, status)
        await self.save(identity)

    async def discard_identity(self, session_id: UUID, identity_id: UUID) -> None:
        """Soft-deletes an identity and detaches it from its user."""
        self._log.info("iam.identity.discard start", identity_id=str(identity_id))
        row = await self._identity_row(identity_id)
        await self._require_self_or_admin(session_id, row.user_id)
        user = await self._user(row.user_id)
        login_identities = await self._view.list_identities(row.user_id)
        if len(login_identities) <= 1:
            msg = "the last login identity of a user cannot be removed"
            raise LastLoginIdentityError(msg)
        identity = await self._identity_aggregate(identity_id)
        identity.discard()
        user.detach_identity(identity_id)
        await self.save(identity, user)
        self._log.info("iam.identity.discard done", identity_id=str(identity_id))

    async def list_identities(self, session_id: UUID, user_id: UUID) -> list[IdentityRow]:
        """Returns the identities of a user."""
        await self._require_self_or_admin(session_id, user_id)
        return await self._view.list_identities(user_id)

    # -- credentials --------------------------------------------------------

    async def change_own_password(
        self,
        session_id: UUID,
        old_password: str,
        new_password: str,
    ) -> None:
        """Changes the password of the identity behind the session."""
        self._log.info("iam.password.change start")
        session = await self._require_session(session_id)
        if session.identity_type != "PASSWORD":
            msg = "only a password session can change a password"
            raise IdentityInvariantError(msg)
        password_hash = await self._view.get_password_hash(session.identity_id)
        if password_hash is None or not self._verify_password(old_password, password_hash):
            msg = "the current password is not valid"
            raise CredentialError(msg)
        self._validate_password(new_password)
        identity = await self._identity_aggregate(session.identity_id)
        identity.change_password(self._hash_password(new_password))
        await self.save(identity)
        self._log.info("iam.password.change done", identity_id=str(session.identity_id))

    async def change_user_password_via_admin(
        self,
        session_id: UUID,
        login: str,
        new_password: str,
    ) -> None:
        """Resets the password of a user without the current password."""
        self._log.info("iam.password.reset start", login=login)
        await self._require_system_admin(session_id)
        self._validate_password(new_password)
        identity_row = await self._view.find_password_identity(login)
        if identity_row is None:
            msg = "no password identity matches the given login"
            raise UnknownIdentityError(msg)
        identity = await self._identity_aggregate(identity_row.identity_id)
        identity.change_password(self._hash_password(new_password))
        await self.save(identity)
        self._log.info("iam.password.reset done", identity_id=str(identity.id))

    async def create_api_key(
        self,
        session_id: UUID,
        user_id: UUID,
        scopes: list[str],
        expires_at: datetime | None = None,
    ) -> ApiKeySecret:
        """Creates an API key and returns its plaintext secret once."""
        self._log.info("iam.api_key.create start", user_id=str(user_id))
        session = await self._require_session(session_id)
        caller = await self._require_self_or_admin(session_id, user_id)
        await self._ensure_scopes_allowed(caller, user_id, session.tenant_id, scopes)
        user = await self._user(user_id)
        identity = await self._api_key_identity(user)
        live = [key for key in user_api_keys(identity) if key.status == "ACTIVE"]
        if len(live) >= self._options.max_api_keys:
            msg = f"user {user_id} already has {len(live)} API keys"
            raise IamValidationError(msg)
        key_id = uuid4()
        secret = self._new_api_key_secret()
        identity.add_api_key(
            key_id,
            self._api_key_prefix(secret),
            self._hash_api_key(secret),
            scopes=tuple(scopes),
            created_at=datetime.now(UTC),
            expires_at=expires_at,
        )
        if user.identities.get(identity.id) is None:
            user.attach_identity(identity.id, "API_KEY", API_KEY_PROVIDER)
            await self.save(identity, user)
        else:
            await self.save(identity)
        self._log.info("iam.api_key.create done", key_id=str(key_id))
        return ApiKeySecret(key_id=key_id, secret=secret)

    async def rotate_api_key(
        self,
        session_id: UUID,
        user_id: UUID,
        key_id: UUID,
        grace_period: timedelta,
    ) -> ApiKeySecret:
        """Replaces an active API key and returns the new secret once."""
        self._log.info("iam.api_key.rotate start", key_id=str(key_id))
        await self._require_self_or_admin(session_id, user_id)
        if grace_period > timedelta(days=self._options.api_key_grace_max_days):
            msg = "the grace period is longer than allowed"
            raise IamValidationError(msg)
        key = await self._view.get_api_key(key_id)
        if key is None or key.user_id != user_id:
            msg = f"API key {key_id} does not exist"
            raise UnknownIdentityError(msg)
        identity = await self._identity_aggregate(key.identity_id)
        new_key_id = uuid4()
        secret = self._new_api_key_secret()
        identity.rotate_api_key(
            key_id,
            new_key_id,
            self._api_key_prefix(secret),
            self._hash_api_key(secret),
            datetime.now(UTC) + grace_period,
            created_at=datetime.now(UTC),
        )
        await self.save(identity)
        self._log.info("iam.api_key.rotate done", key_id=str(new_key_id))
        return ApiKeySecret(key_id=new_key_id, secret=secret)

    async def revoke_api_key(self, session_id: UUID, user_id: UUID, key_id: UUID) -> None:
        """Revokes an API key."""
        self._log.info("iam.api_key.revoke start", key_id=str(key_id))
        await self._require_self_or_admin(session_id, user_id)
        key = await self._view.get_api_key(key_id)
        if key is None or key.user_id != user_id:
            msg = f"API key {key_id} does not exist"
            raise UnknownIdentityError(msg)
        identity = await self._identity_aggregate(key.identity_id)
        identity.revoke_api_key(key_id, datetime.now(UTC))
        await self.save(identity)
        self._log.info("iam.api_key.revoke done", key_id=str(key_id))

    async def list_api_keys(self, session_id: UUID, user_id: UUID) -> list[ApiKeyRow]:
        """Returns the API keys of a user."""
        await self._require_self_or_admin(session_id, user_id)
        return await self._view.list_api_keys(user_id)

    # -- authentication -----------------------------------------------------

    async def authenticate_password(
        self,
        login: str,
        plain_password: str,
        tenant_id: UUID | None = None,
    ) -> SessionRef:
        """Authenticates a login and password and issues a session."""
        self._log.info("iam.authenticate.password start", login=login)
        identity_row = await self._view.find_password_identity(login)
        if identity_row is None:
            msg = "invalid credentials"
            raise AuthenticationError(msg)
        password_hash = await self._view.get_password_hash(identity_row.identity_id)
        if password_hash is None or not self._verify_password(plain_password, password_hash):
            msg = "invalid credentials"
            raise AuthenticationError(msg)
        await self._ensure_can_authenticate(identity_row, tenant_id)
        session = await self._issue_session(
            identity_row,
            tenant_id,
            self._options.password_session_minutes,
            api_key_id=None,
        )
        self._log.info("iam.authenticate.password done", session_id=str(session.session_id))
        return session

    async def authenticate_api_key(self, raw_key: str) -> SessionRef:
        """Authenticates a raw API key and issues a session."""
        self._log.info("iam.authenticate.api_key start")
        candidates = await self._view.find_api_keys_by_prefix(self._api_key_prefix(raw_key))
        now = datetime.now(UTC)
        for key in candidates:
            if not hmac.compare_digest(key.secret_hash, self._hash_api_key(raw_key)):
                continue
            if key.status not in ("ACTIVE", "GRACE"):
                continue
            if key.status == "GRACE" and (
                key.grace_until is None or now > _as_utc(key.grace_until)
            ):
                continue
            if key.expires_at is not None and now >= _as_utc(key.expires_at):
                continue
            identity_row = await self._identity_row(key.identity_id)
            await self._ensure_can_authenticate(identity_row, None)
            session = await self._issue_session(
                identity_row,
                None,
                self._options.api_key_session_minutes,
                api_key_id=key.key_id,
            )
            self._log.info("iam.authenticate.api_key done", session_id=str(session.session_id))
            return session
        msg = "invalid credentials"
        raise AuthenticationError(msg)

    async def authenticate_oidc(
        self,
        issuer: str,
        subject: str,
        tenant_id: UUID | None = None,
    ) -> SessionRef | UnboundOidcIdentity:
        """Maps an OIDC subject to an identity and issues a session.

        The caller (the host's OIDC adapter, see
        :class:`etlalchemy.iam.ports.oidc.OidcClient`) has already exchanged the
        code, validated the signature and fetched the subject; this method only
        resolves the identity and issues the session. An unknown subject returns
        :class:`UnboundOidcIdentity` instead of raising: there is no first-login
        auto-registration, so the host has to ask the user to log in and bind the
        identity explicitly.
        """
        self._log.info("iam.authenticate.oidc start", issuer=issuer)
        identity_row = await self._view.find_oidc_identity(issuer, subject)
        if identity_row is None:
            return UnboundOidcIdentity(issuer=issuer, subject=subject)
        if identity_row.provider_id is None:
            msg = f"OIDC identity {identity_row.identity_id} has no provider"
            raise IdentityInvariantError(msg)
        provider = await self._provider_row(identity_row.provider_id)
        if provider.status != "ENABLED":
            msg = "the identity provider is not available"
            raise IdentityUnavailableError(msg)
        if provider.tenant_id is not None and provider.tenant_id != tenant_id:
            msg = f"auth provider {provider.provider_key!r} serves tenant {provider.tenant_id} only"
            raise IdentityUnavailableError(msg)
        await self._ensure_can_authenticate(identity_row, tenant_id)
        session = await self._issue_session(
            identity_row,
            tenant_id,
            self._options.oidc_session_minutes,
            api_key_id=None,
        )
        self._log.info("iam.authenticate.oidc done", session_id=str(session.session_id))
        return session

    async def refresh_session(self, session_id: UUID) -> SessionRef:
        """Extends a session and returns the refreshed reference."""
        session_row = await self._valid_session_row(session_id)
        identity_row = await self._identity_row(session_row.identity_id)
        if identity_row.credential_version != session_row.credential_version:
            await self._revoke_stale(session_id, "credential_changed")
            msg = "the session is no longer valid"
            raise SessionExpiredError(msg)
        minutes = self._session_minutes(session_row.identity_type)
        now = datetime.now(UTC)
        session = await self._session_aggregate(session_id)
        session.refresh(now + timedelta(minutes=minutes), last_seen_at=now)
        await self.save(session)
        return SessionRef(
            session_id=session.id,
            identity_id=session.identity_id,
            user_id=session.user_id,
            tenant_id=session.tenant_id,
            expires_at=session.expires_at,
        )

    async def revoke_session(self, session_id: UUID, reason: str = "logout") -> None:
        """Revokes a session."""
        session = await self._session_aggregate(session_id)
        session.revoke(reason)
        await self.save(session)

    async def get_session(self, session_id: UUID) -> SessionRef:
        """Returns the current state of a session."""
        row = await self._valid_session_row(session_id)
        return SessionRef(
            session_id=row.session_id,
            identity_id=row.identity_id,
            user_id=row.user_id,
            tenant_id=row.tenant_id,
            expires_at=_as_utc(row.expires_at),
        )

    async def validate_session(self, session_id: UUID) -> SessionRef:
        """Validates a session for authentication and returns its reference.

        Unlike :meth:`authorize`, this method performs no permission check: it only
        decides whether the session, its identity, its user, the tenant and the
        membership are still usable. Delivery layers call it for every bearer token
        so a revoked session, a suspended user or a changed credential stops
        working immediately.

        Args:
            session_id: Id of the session to validate.

        Returns:
            The session reference, including the system administrator flag.

        Raises:
            AuthenticationError: If the session, identity, user, tenant or
                membership is unavailable, or if the credential version moved on.
            SessionRevokedError: If the session was revoked.
            SessionExpiredError: If the session has expired.
        """
        row = await self._valid_session_row(session_id)
        reason, user, _tenant_ids = await self._session_checks(row)
        if reason is not None or user is None:
            msg = "the session is no longer usable"
            raise AuthenticationError(msg)
        return SessionRef(
            session_id=row.session_id,
            identity_id=row.identity_id,
            user_id=row.user_id,
            tenant_id=row.tenant_id,
            expires_at=_as_utc(row.expires_at),
            is_system_admin=user.is_system_admin,
        )

    # -- groups -------------------------------------------------------------

    async def create_group(
        self,
        session_id: UUID,
        tenant_id: UUID,
        name: str,
        parent_group_id: UUID | None = None,
        description: str = "",
    ) -> UUID:
        """Creates a group in a tenant and returns its id."""
        self._log.info("iam.group.create start", tenant_id=str(tenant_id), name=name)
        session = await self._require_session(session_id)
        await self._require_permission(session, tenant_id, "group", "create")
        tenant = await self._tenant(tenant_id)
        if tenant.status != "ACTIVE":
            msg = f"tenant {tenant_id} is suspended"
            raise TenantSuspendedError(msg)
        parent: Group | None = None
        if parent_group_id is not None:
            parent = await self._group_aggregate(parent_group_id)
            if parent.tenant_id != tenant_id:
                msg = f"group {parent_group_id} does not exist in tenant {tenant_id}"
                raise UnknownGroupError(msg)
        if await self._view.find_group_by_name(tenant_id, parent_group_id, name) is not None:
            msg = f"group {name!r} already exists under that parent"
            raise DuplicateGroupError(msg)
        group = Group(
            tenant_id=tenant_id,
            name=name,
            description=description,
            parent_group_id=parent_group_id,
        )
        if parent is None:
            await self.save(group)
        else:
            ancestors = await self._ancestor_chain(parent)
            self._check_depth(ancestors)
            parent.add_member(
                group.id,
                "group",
                datetime.now(UTC),
                ancestors=ancestors,
            )
            await self.save(group, parent)
        self._log.info("iam.group.create done", group_id=str(group.id))
        return group.id

    async def change_group(
        self,
        session_id: UUID,
        group_id: UUID,
        name: str | None = None,
        description: str | None = None,
    ) -> None:
        """Changes the name or description of a group."""
        row = await self._group_row(group_id)
        session = await self._require_session(session_id)
        await self._require_permission(session, row.tenant_id, "group", "update")
        if name is not None:
            existing = await self._view.find_group_by_name(
                row.tenant_id,
                row.parent_group_id,
                name,
            )
            if existing is not None and existing.group_id != group_id:
                msg = f"group {name!r} already exists under that parent"
                raise DuplicateGroupError(msg)
        group = await self._group_aggregate(group_id)
        group.change(name, description)
        await self.save(group)

    async def set_group_parent(
        self,
        session_id: UUID,
        group_id: UUID,
        new_parent_id: UUID | None,
    ) -> None:
        """Moves a group below another group, rejecting a cycle."""
        self._log.info("iam.group.move start", group_id=str(group_id))
        row = await self._group_row(group_id)
        session = await self._require_session(session_id)
        await self._require_permission(session, row.tenant_id, "group", "update")
        new_parent: Group | None = (
            None if new_parent_id is None else await self._group_aggregate(new_parent_id)
        )
        ancestors = await self._ancestor_chain(new_parent)
        self._check_depth(ancestors)
        if group_id in ancestors:
            msg = f"moving group {group_id} below {new_parent_id} creates a cycle"
            raise GroupCycleError(msg)
        group = await self._group_aggregate(group_id)
        group.change_parent(new_parent_id, ancestors=ancestors)
        savable: list[Group] = [group]
        if row.parent_group_id is not None:
            old_parent = await self._group_aggregate(row.parent_group_id)
            if group_id in old_parent.members:
                old_parent.remove_member(group_id)
                savable.append(old_parent)
        if new_parent is not None and group_id not in new_parent.members:
            new_parent.add_member(group_id, "group", datetime.now(UTC), ancestors=ancestors)
            savable.append(new_parent)
        await self.save(*savable)
        self._log.info("iam.group.move done", group_id=str(group_id))

    async def add_group_member(
        self,
        session_id: UUID,
        group_id: UUID,
        member_id: UUID,
        member_kind: str | None = None,
    ) -> None:
        """Adds a user or a child group to a group."""
        self._log.info("iam.group.member.add start", group_id=str(group_id))
        group_row = await self._group_row(group_id)
        session = await self._require_session(session_id)
        await self._require_permission(session, group_row.tenant_id, "group", "manage_members")
        kind = await self._member_kind(group_row.tenant_id, member_id, member_kind)
        if kind == "user":
            tenant = await self._tenant(group_row.tenant_id)
            if not tenant.has_member(member_id):
                msg = f"user {member_id} is not an active member of the tenant"
                raise UnknownMembershipError(msg)
        group = await self._group_aggregate(group_id)
        ancestors = await self._ancestor_chain(group)
        self._check_depth(ancestors)
        group.add_member(
            member_id,
            kind,
            datetime.now(UTC),
            ancestors=ancestors,
        )
        await self.save(group)
        self._log.info("iam.group.member.add done", group_id=str(group_id))

    async def remove_group_member(
        self,
        session_id: UUID,
        group_id: UUID,
        member_id: UUID,
    ) -> None:
        """Removes a member from a group."""
        group_row = await self._group_row(group_id)
        session = await self._require_session(session_id)
        await self._require_permission(session, group_row.tenant_id, "group", "manage_members")
        group = await self._group_aggregate(group_id)
        group.remove_member(member_id)
        await self.save(group)

    async def discard_group(self, session_id: UUID, group_id: UUID) -> None:
        """Soft-deletes a group and every group below it."""
        self._log.info("iam.group.discard start", group_id=str(group_id))
        row = await self._group_row(group_id)
        session = await self._require_session(session_id)
        await self._require_permission(session, row.tenant_id, "group", "delete")
        groups = {item.group_id: item for item in await self._view.list_groups(row.tenant_id)}
        doomed = {group_id, *self._descendants(group_id, groups)}
        aggregates: list[Group] = []
        for identifier in doomed:
            group = await self._group_aggregate(identifier)
            group.discard()
            aggregates.append(group)
        await self.save(*aggregates)
        self._log.info("iam.group.discard done", groups=len(doomed))

    async def list_groups(self, session_id: UUID, tenant_id: UUID) -> list[GroupRow]:
        """Returns the live groups of a tenant."""
        await self._require_session(session_id)
        return await self._view.list_groups(tenant_id)

    async def list_group_members(
        self,
        session_id: UUID,
        group_id: UUID,
        recursive: bool = False,
    ) -> list[GroupMemberRow]:
        """Returns the members of a group, optionally including its subgroups."""
        row = await self._group_row(group_id)
        await self._require_session(session_id)
        members = await self._view.list_group_members(row.tenant_id)
        if not recursive:
            return [member for member in members if member.group_id == group_id]
        groups = {item.group_id: item for item in await self._view.list_groups(row.tenant_id)}
        included = {group_id, *self._descendants(group_id, groups)}
        return [member for member in members if member.group_id in included]

    async def grant_group_permission(
        self,
        session_id: UUID,
        tenant_id: UUID,
        group_id: UUID,
        obj: str,
        act: str,
    ) -> None:
        """Grants a permission to a group."""
        self._log.info("iam.group.permission.grant start", group_id=str(group_id))
        session = await self._require_session(session_id)
        await self._require_permission(session, tenant_id, "permission", "grant")
        row = await self._group_row(group_id)
        if row.tenant_id != tenant_id:
            msg = f"group {group_id} does not belong to tenant {tenant_id}"
            raise UnknownGroupError(msg)
        Permission.parse(f"{obj}:{act}")
        group = await self._group_aggregate(group_id)
        if (obj, act) in group.permission_grants:
            msg = f"group {group_id} already holds {obj}:{act}"
            raise DuplicatePermissionGrantError(msg)
        group.grant_permission(obj, act)
        await self.save(group)
        self._log.info("iam.group.permission.grant done", group_id=str(group_id))

    async def revoke_group_permission(
        self,
        session_id: UUID,
        tenant_id: UUID,
        group_id: UUID,
        obj: str,
        act: str,
    ) -> None:
        """Revokes a permission from a group."""
        session = await self._require_session(session_id)
        await self._require_permission(session, tenant_id, "permission", "grant")
        group = await self._group_aggregate(group_id)
        group.revoke_permission(obj, act)
        await self.save(group)

    # -- authorization ------------------------------------------------------

    async def authorize(self, session_id: UUID, obj: str, act: str) -> bool:
        """Returns whether the session may perform the action on the object."""
        session = await self._view.get_session(session_id)
        if session is None:
            return False
        reason = await self._denial_reason(session, obj, act)
        if reason is None:
            return True
        await self._record_denial(session, obj, act, reason)
        return False

    async def effective_permissions(
        self,
        session_id: UUID,
    ) -> frozenset[Permission]:
        """Returns the permissions the session actually exercises."""
        session = await self._valid_session_row(session_id)
        user = await self._view.get_user(session.user_id)
        if user is not None and user.is_system_admin:
            return frozenset({Permission(resource="*", action="*")})
        if session.tenant_id is not None:
            tenant_ids = [session.tenant_id]
        else:
            memberships = await self._view.list_memberships(session.user_id)
            tenant_ids = [
                membership.tenant_id for membership in memberships if membership.status == "ACTIVE"
            ]
        permissions: set[Permission] = set()
        for tenant_id in tenant_ids:
            permissions.update(
                await self._authorizer.implicit_permissions(
                    self._view,
                    session.user_id,
                    tenant_id,
                ),
            )
        if session.api_key_id is None:
            return frozenset(permissions)
        key = await self._view.get_api_key(session.api_key_id)
        if key is None:
            return frozenset()
        return frozenset(
            permission
            for permission in permissions
            if self._scope_covers(key.scopes, permission.resource, permission.action)
        )

    # -- auth providers -----------------------------------------------------

    async def create_auth_provider(
        self,
        session_id: UUID,
        provider_key: str,
        kind: str,
        display_name: str,
        config: dict[str, str],
        tenant_id: UUID | None = None,
    ) -> UUID:
        """Creates an auth provider and returns its id."""
        self._log.info("iam.provider.create start", provider_key=provider_key)
        await self._require_system_admin(session_id)
        if await self._view.find_provider_by_key(provider_key) is not None:
            msg = f"auth provider {provider_key!r} already exists"
            raise DuplicateAuthProviderError(msg)
        if tenant_id is not None:
            await self._tenant(tenant_id)
        provider = AuthProvider(
            provider_key=provider_key,
            kind=kind,
            display_name=display_name,
            config=config,
            tenant_id=tenant_id,
        )
        await self.save(provider)
        self._log.info("iam.provider.create done", provider_id=str(provider.id))
        return provider.id

    async def update_auth_provider_config(
        self,
        session_id: UUID,
        provider_id: UUID,
        config: dict[str, str],
    ) -> None:
        """Replaces the configuration of an auth provider.

        Changing ``issuer`` while identities are bound would orphan every binding
        (the projection looks identities up by issuer), so it is rejected; discard
        the provider and create it again instead.
        """
        await self._require_system_admin(session_id)
        provider = await self._provider_aggregate(provider_id)
        new_config = OidcConfig.from_mapping(dict(config))
        current_issuer = provider.config.get("issuer", "")
        if new_config.issuer != current_issuer and await self._view.count_provider_identities(
            provider_id,
        ):
            msg = "the issuer cannot change while identities are bound to the provider"
            raise IamValidationError(msg)
        provider.update_config(config)
        await self.save(provider)

    async def change_auth_provider(
        self,
        session_id: UUID,
        provider_id: UUID,
        display_name: str | None = None,
        status: str | None = None,
    ) -> None:
        """Changes the display name or status of an auth provider."""
        await self._require_system_admin(session_id)
        provider = await self._provider_aggregate(provider_id)
        provider.change(display_name, status)
        await self.save(provider)

    async def discard_auth_provider(
        self,
        session_id: UUID,
        provider_id: UUID,
        force: bool = False,
    ) -> None:
        """Soft-deletes an auth provider.

        The "still in use" check reads the projection, so it is eventually
        consistent: a binding created concurrently may slip through. With
        ``force=True`` the provider disappears from the view immediately and every
        identity bound to it fails its next ``authenticate_oidc`` with
        ``IdentityUnavailableError``; existing sessions are not revoked, because a
        provider is not a session subject.
        """
        self._log.info("iam.provider.discard start", provider_id=str(provider_id))
        await self._require_system_admin(session_id)
        if not force and await self._view.count_provider_identities(provider_id) > 0:
            msg = "the auth provider is still used by at least one identity"
            raise ProviderInUseError(msg)
        provider = await self._provider_aggregate(provider_id)
        provider.discard()
        await self.save(provider)
        self._log.info("iam.provider.discard done", provider_id=str(provider_id))

    async def list_auth_providers(self, session_id: UUID) -> list[ProviderRow]:
        """Returns every live auth provider."""
        await self._require_system_admin(session_id)
        return await self._view.list_providers()

    async def provider_client_secret(self, provider_id: UUID) -> str:
        """Returns the resolved client secret of an auth provider.

        This is an anonymous runtime path, like :meth:`authenticate_oidc`: the host
        OIDC adapter resolves the secret during the authorization code exchange,
        before any session exists, so the method cannot be session-guarded. Only
        the reference is stored in the event stream; the value is read per call and
        must never be logged or cached.

        Args:
            provider_id: ID of the auth provider.

        Returns:
            The client secret resolved from ``client_secret_ref``.

        Raises:
            UnknownAuthProviderError: If the provider is missing or discarded.
            IamValidationError: If the reference is missing or cannot be resolved.
        """
        provider = await self._provider_row(provider_id)
        reference = provider.config.get("client_secret_ref", "")
        if not reference:
            msg = f"auth provider {provider.provider_key!r} has no client secret reference"
            raise IamValidationError(msg)
        try:
            return self._secrets.resolve(reference)
        except LookupError as exc:
            msg = f"cannot resolve the client secret of {provider.provider_key!r}: {exc}"
            raise IamValidationError(msg) from exc

    async def list_audit_events(
        self,
        session_id: UUID,
        limit: int = 50,
        offset: int = 0,
        action: str | None = None,
    ) -> list[AuditRow]:
        """Returns audit records, newest first."""
        await self._require_system_admin(session_id)
        return await self._view.list_audit_events(limit=limit, offset=offset, action=action)

    # -- decision helpers ---------------------------------------------------

    async def _session_checks(
        self,
        session: SessionRow,
    ) -> tuple[str | None, UserRow | None, list[UUID]]:
        """Returns why a session is unusable, its user and its tenant scope.

        Covers everything that is independent of the requested action, so both
        :meth:`authorize` and :meth:`validate_session` share one implementation.
        An empty tenant list is reported to the caller instead of being rejected
        here: a system administrator may legitimately belong to no tenant.
        """
        now = datetime.now(UTC)
        if session.status != "ACTIVE":
            return "session_revoked", None, []
        if now >= _as_utc(session.expires_at):
            return "session_expired", None, []
        identity = await self._view.get_identity(session.identity_id)
        if identity is None or identity.status != "ACTIVE":
            return "identity_unavailable", None, []
        if identity.credential_version != session.credential_version:
            await self._revoke_stale(session.session_id, "credential_changed")
            return "credential_changed", None, []
        user = await self._view.get_user(session.user_id)
        if user is None or user.status != "ACTIVE":
            return "user_inactive", None, []
        if session.tenant_id is not None:
            tenant = await self._view.get_tenant(session.tenant_id)
            if tenant is None or tenant.status != "ACTIVE":
                return "tenant_unavailable", user, []
            membership = await self._view.get_membership(session.tenant_id, session.user_id)
            if membership is None or membership.status != "ACTIVE":
                return "not_a_member", user, []
            return None, user, [session.tenant_id]
        memberships = await self._view.list_memberships(session.user_id)
        tenant_ids = [
            membership.tenant_id for membership in memberships if membership.status == "ACTIVE"
        ]
        return None, user, tenant_ids

    async def _denial_reason(self, session: SessionRow, obj: str, act: str) -> str | None:
        """Returns why the session is denied, or ``None`` when it is allowed."""
        reason, user, tenant_ids = await self._session_checks(session)
        if reason is not None:
            return reason
        if user is None:  # pragma: no cover - _session_checks guarantees a user
            return "user_inactive"
        if user.is_system_admin:
            return None
        if session.api_key_id is not None:
            key = await self._view.get_api_key(session.api_key_id)
            if not self._key_is_usable(key, datetime.now(UTC)):
                return "api_key_unavailable"
            if key is not None and not self._scope_covers(key.scopes, obj, act):
                return "outside_scopes"
        if not tenant_ids:
            return "not_a_member"
        for tenant_id in tenant_ids:
            if await self._authorizer.enforce(self._view, session.user_id, tenant_id, obj, act):
                return None
        return "no_matching_policy"

    async def _record_denial(
        self,
        session: SessionRow,
        obj: str,
        act: str,
        reason: str,
    ) -> None:
        """Writes the denial to the session stream, never failing the check."""
        if not self._options.record_denied_authorizations:
            return
        try:
            aggregate = await self._session_aggregate(session.session_id)
            aggregate.deny(
                obj,
                act,
                reason,
                actor_user_id=session.user_id,
                actor_identity_id=session.identity_id,
            )
            await self.save(aggregate)
        except Exception:  # auditing must not change the decision
            self._log.exception("iam.authorize.audit.failed", session_id=str(session.session_id))

    async def _revoke_stale(self, session_id: UUID, reason: str) -> None:
        """Revokes a session whose credential version moved on."""
        try:
            aggregate = await self._session_aggregate(session_id)
            aggregate.revoke(reason)
            await self.save(aggregate)
        except Exception:  # the caller already decided to deny
            self._log.exception("iam.authorize.revoke.failed", session_id=str(session_id))

    # -- loading helpers ----------------------------------------------------

    async def _require_session(self, session_id: UUID) -> SessionRow:
        """Returns the session row of an active, unexpired session."""
        row = await self._valid_session_row(session_id)
        if row.status != "ACTIVE":
            msg = "the session is not active"
            raise SessionRevokedError(msg)
        return row

    async def _valid_session_row(self, session_id: UUID) -> SessionRow:
        """Returns a session row, raising when it is unknown or expired."""
        row = await self._view.get_session(session_id)
        if row is None:
            msg = "the session does not exist"
            raise AuthenticationError(msg)
        if row.status != "ACTIVE":
            msg = "the session is not active"
            raise SessionRevokedError(msg)
        if datetime.now(UTC) >= _as_utc(row.expires_at):
            msg = "the session is expired"
            raise SessionExpiredError(msg)
        return row

    async def _require_system_admin(self, session_id: UUID) -> UserRow:
        """Returns the caller, requiring the system administrator flag."""
        session = await self._require_session(session_id)
        user = await self._view.get_user(session.user_id)
        if user is None or not user.is_system_admin:
            msg = "the caller is not a system administrator"
            raise PermissionDeniedError(msg)
        return user

    async def _require_self_or_admin(self, session_id: UUID, user_id: UUID) -> UserRow:
        """Returns the caller, requiring it to be the user or a system admin."""
        session = await self._require_session(session_id)
        caller = await self._view.get_user(session.user_id)
        if caller is None:
            msg = "the caller does not exist"
            raise AuthenticationError(msg)
        if caller.user_id != user_id and not caller.is_system_admin:
            msg = "the caller may not act on this user"
            raise PermissionDeniedError(msg)
        return caller

    async def _require_permission(
        self,
        session: SessionRow,
        tenant_id: UUID,
        resource: str,
        action: str,
    ) -> None:
        """Requires a permission on a tenant-scoped resource."""
        user = await self._view.get_user(session.user_id)
        if user is not None and user.is_system_admin:
            return
        allowed = await self._authorizer.enforce(
            self._view,
            session.user_id,
            tenant_id,
            resource,
            action,
        )
        if not allowed:
            msg = f"the caller may not {action} {resource} in tenant {tenant_id}"
            raise PermissionDeniedError(msg)

    async def _ensure_unique_user(
        self,
        username: str | None,
        email: str | None,
    ) -> None:
        """Rejects a username or email that a live user already uses."""
        if username is not None:
            existing = await self._view.find_user_by_login(username)
            if existing is not None and existing.username.lower() == username:
                msg = f"username {username!r} already exists"
                raise DuplicateUserError(msg)
        if email is not None:
            existing = await self._view.find_user_by_login(email)
            if existing is not None and existing.email.lower() == email:
                msg = f"email {email!r} already exists"
                raise DuplicateEmailError(msg)

    async def _ensure_can_authenticate(
        self,
        identity_row: IdentityRow,
        tenant_id: UUID | None,
    ) -> None:
        """Rejects a suspended identity or user, and a missing membership."""
        if identity_row.status != "ACTIVE":
            msg = "invalid credentials"
            raise AuthenticationError(msg)
        user = await self._view.get_user(identity_row.user_id)
        if user is None:
            msg = "invalid credentials"
            raise AuthenticationError(msg)
        if user.status != "ACTIVE":
            msg = f"user {user.username!r} is suspended"
            raise UserSuspendedError(msg)
        if tenant_id is None:
            return
        tenant = await self._view.get_tenant(tenant_id)
        if tenant is None or tenant.status != "ACTIVE":
            msg = f"tenant {tenant_id} is not active"
            raise TenantSuspendedError(msg)
        membership = await self._view.get_membership(tenant_id, user.user_id)
        if membership is None or membership.status != "ACTIVE":
            msg = f"user {user.username!r} is not a member of tenant {tenant_id}"
            raise UnknownMembershipError(msg)

    def _session_minutes(self, identity_type: str) -> int:
        """Returns the session lifetime of an identity type.

        A refresh uses the same lifetime the identity authenticated with, so an
        OIDC session never inherits the password TTL.
        """
        if identity_type == "API_KEY":
            return self._options.api_key_session_minutes
        if identity_type == "OIDC":
            return self._options.oidc_session_minutes
        return self._options.password_session_minutes

    async def _issue_session(
        self,
        identity_row: IdentityRow,
        tenant_id: UUID | None,
        ttl_minutes: int,
        api_key_id: UUID | None,
    ) -> SessionRef:
        """Creates a session aggregate for an authenticated identity."""
        now = datetime.now(UTC)
        expires_at = now + timedelta(minutes=ttl_minutes)
        session = Session(
            identity_id=identity_row.identity_id,
            user_id=identity_row.user_id,
            expires_at=expires_at,
            identity_type=identity_row.identity_type,
            credential_version=identity_row.credential_version,
            tenant_id=tenant_id,
            api_key_id=api_key_id,
        )
        await self.save(session)
        return SessionRef(
            session_id=session.id,
            identity_id=session.identity_id,
            user_id=session.user_id,
            tenant_id=session.tenant_id,
            expires_at=session.expires_at,
        )

    async def _tenant(self, tenant_id: UUID) -> Tenant:
        """Loads a tenant aggregate."""
        try:
            tenant: Tenant = await self.repository.get(tenant_id)
        except Exception as exc:
            msg = f"tenant {tenant_id} does not exist"
            raise UnknownTenantError(msg) from exc
        return tenant

    async def _user(self, user_id: UUID) -> User:
        """Loads a user aggregate."""
        try:
            user: User = await self.repository.get(user_id)
        except Exception as exc:
            msg = f"user {user_id} does not exist"
            raise UnknownUserError(msg) from exc
        return user

    async def _identity_aggregate(self, identity_id: UUID) -> Identity:
        """Loads an identity aggregate."""
        try:
            identity: Identity = await self.repository.get(identity_id)
        except Exception as exc:
            msg = f"identity {identity_id} does not exist"
            raise UnknownIdentityError(msg) from exc
        return identity

    async def _session_aggregate(self, session_id: UUID) -> Session:
        """Loads a session aggregate."""
        try:
            session: Session = await self.repository.get(session_id)
        except Exception as exc:
            msg = f"session {session_id} does not exist"
            raise AuthenticationError(msg) from exc
        return session

    async def _group_aggregate(self, group_id: UUID) -> Group:
        """Loads a group aggregate."""
        try:
            group: Group = await self.repository.get(group_id)
        except Exception as exc:
            msg = f"group {group_id} does not exist"
            raise UnknownGroupError(msg) from exc
        return group

    async def _provider_aggregate(self, provider_id: UUID) -> AuthProvider:
        """Loads an auth provider aggregate."""
        try:
            provider: AuthProvider = await self.repository.get(provider_id)
        except Exception as exc:
            msg = f"auth provider {provider_id} does not exist"
            raise UnknownAuthProviderError(msg) from exc
        return provider

    async def _group_row(self, group_id: UUID) -> GroupRow:
        """Returns the state of a group, read from its own event stream."""
        group = await self._group_aggregate(group_id)
        return GroupRow(
            group_id=group.id,
            tenant_id=group.tenant_id,
            name=group.name,
            description=group.description,
            parent_group_id=group.parent_group_id,
        )

    async def _identity_row(self, identity_id: UUID) -> IdentityRow:
        """Returns the state of an identity, read from its own event stream."""
        identity = await self._identity_aggregate(identity_id)
        return IdentityRow(
            identity_id=identity.id,
            user_id=identity.user_id,
            identity_type=identity.identity_type,
            provider=identity.provider,
            display_name=identity.display_name,
            status=identity.status,
            credential_version=identity.credential_version,
            provider_id=identity.provider_id,
            oidc_issuer=identity.oidc_issuer,
            oidc_subject=identity.oidc_subject,
            last_used_at=None,
        )

    async def _provider_row(self, provider_id: UUID) -> ProviderRow:
        """Returns the state of a provider, read from its own event stream.

        Reading the aggregate keeps the check immediate (no projection lag) and
        lets a discarded provider be rejected: ``status`` keeps its last value
        after a discard, so the flag is checked explicitly.
        """
        provider = await self._provider_aggregate(provider_id)
        if provider.is_discarded:
            msg = f"auth provider {provider_id} does not exist"
            raise UnknownAuthProviderError(msg)
        return ProviderRow(
            provider_id=provider.id,
            provider_key=provider.provider_key,
            kind=provider.kind,
            display_name=provider.display_name,
            tenant_id=provider.tenant_id,
            config=dict(provider.config),
            status=provider.status,
        )

    async def _api_key_identity(self, user: User) -> Identity:
        """Returns the API key identity of a user, creating it when missing."""
        for identity_id, ref in user.identities.items():
            if ref.identity_type == "API_KEY":
                return await self._identity_aggregate(identity_id)
        identity = Identity(
            user_id=user.id,
            identity_type="API_KEY",
            provider=API_KEY_PROVIDER,
            display_name="API keys",
        )
        return identity

    async def _member_kind(
        self,
        tenant_id: UUID,
        member_id: UUID,
        member_kind: str | None,
    ) -> GroupMemberKind:
        """Resolves whether a member id is a user or a group of the tenant."""
        if member_kind in ("user", "group"):
            return member_kind  # type: ignore[return-value]
        if await self._view.get_user(member_id) is not None:
            return "user"
        group = await self._view.get_group(member_id)
        if group is not None and group.tenant_id == tenant_id:
            return "group"
        msg = f"member {member_id} is neither a user nor a group of tenant {tenant_id}"
        raise UnknownGroupError(msg)

    async def _ancestor_chain(self, group: Group | None) -> tuple[UUID, ...]:
        """Returns the ancestor chain of a group, nearest first.

        The chain is walked through the event streams, so a group created in the
        same unit of work is already visible to the cycle check.
        """
        chain: list[UUID] = []
        current = group
        while current is not None and current.id not in chain:
            chain.append(current.id)
            if current.parent_group_id is None:
                break
            current = await self._group_aggregate(current.parent_group_id)
        return tuple(chain)

    def _check_depth(self, ancestors: tuple[UUID, ...]) -> None:
        """Rejects an ancestor chain longer than the configured maximum."""
        if len(ancestors) >= self._options.max_group_depth:
            msg = f"the group hierarchy exceeds {self._options.max_group_depth} levels"
            raise GroupDepthExceededError(msg)

    @staticmethod
    def _descendants(group_id: UUID, groups: dict[UUID, GroupRow]) -> set[UUID]:
        """Returns every group below the given group."""
        found: set[UUID] = set()
        pending = [child for child, row in groups.items() if row.parent_group_id == group_id]
        while pending:
            current = pending.pop()
            if current in found:
                continue
            found.add(current)
            pending.extend(child for child, row in groups.items() if row.parent_group_id == current)
        return found

    async def _ensure_scopes_allowed(
        self,
        caller: UserRow,
        user_id: UUID,
        tenant_id: UUID | None,
        scopes: list[str],
    ) -> None:
        """Rejects scopes the user cannot exercise."""
        if caller.is_system_admin or not scopes:
            return
        permissions = await self._authorizer.implicit_permissions(
            self._view,
            user_id,
            tenant_id,
        )
        for scope in scopes:
            permission = Permission.parse(scope)
            if permission not in permissions:
                msg = f"scope {scope!r} exceeds the permissions of the user"
                raise ScopeExceedsGrantError(msg)

    @staticmethod
    def _scope_covers(
        scopes: list[str] | tuple[str, ...] | frozenset[str], obj: str, act: str
    ) -> bool:
        """Returns whether an API key scope allows the action on the object."""
        required = f"{obj}:{act}"
        for scope in scopes:
            if scope in ("*", "*:*", required):
                return True
            resource, _, action = scope.rpartition(":")
            if resource == obj and action in ("*", act):
                return True
        return False

    @staticmethod
    def _key_is_usable(key: ApiKeyRow | None, now: datetime) -> bool:
        """Returns whether an API key may still issue a request."""
        if key is None or key.status not in ("ACTIVE", "GRACE"):
            return False
        if key.status == "GRACE" and (key.grace_until is None or now > _as_utc(key.grace_until)):
            return False
        return key.expires_at is None or now < _as_utc(key.expires_at)

    def _validate_password(self, plain_password: str) -> None:
        """Rejects a password shorter than the configured minimum."""
        if len(plain_password) < self._options.password_min_length:
            msg = f"password must be at least {self._options.password_min_length} characters"
            raise IamValidationError(msg)

    def _hash_password(self, plain_password: str) -> str:
        """Returns the Argon2id hash of a plaintext password."""
        return self._hasher.hash(plain_password)

    def _verify_password(self, plain_password: str, password_hash: str) -> bool:
        """Returns whether the plaintext password matches the stored hash."""
        return self._hasher.verify(plain_password, password_hash)

    def _hash_api_key(self, secret: str) -> str:
        """Returns the HMAC-SHA256 (or plain SHA-256) digest of a key secret."""
        if self._options.api_key_pepper:
            return hmac.new(
                self._options.api_key_pepper.encode("utf-8"),
                secret.encode("utf-8"),
                hashlib.sha256,
            ).hexdigest()
        return hashlib.sha256(secret.encode("utf-8")).hexdigest()

    @staticmethod
    def _new_api_key_secret() -> str:
        """Returns a new API key secret with at least 128 bits of entropy."""
        return f"iam_ak_{secrets.token_urlsafe(32)}"

    @staticmethod
    def _api_key_prefix(secret: str) -> str:
        """Returns the lookup prefix of an API key secret."""
        return secret[:API_KEY_PREFIX_LENGTH]

    @staticmethod
    def _normalize_email(email: str) -> str:
        """Returns the lowercase, stripped email address."""
        return email.strip().lower()


def user_api_keys(identity: Identity) -> list[ApiKey]:
    """Returns the API keys of an identity, oldest first."""
    return list(identity.api_keys.values())


__all__ = [
    "ApiKeySecret",
    "IamApplication",
    "IamOptions",
    "SessionRef",
    "UnboundOidcIdentity",
]
