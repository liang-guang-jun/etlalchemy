"""Projection that materialises the IAM read model."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from eventsourcing.asyncio.application import AsyncApplication
from eventsourcing.asyncio.projection import AsyncProjectionRunner
from eventsourcing.dispatch import singledispatchmethod
from eventsourcing.persistence import Tracking
from eventsourcing.utils import EnvType, get_topic

from etlalchemy.iam.aggregates.auth_provider import AuthProvider
from etlalchemy.iam.aggregates.group import Group
from etlalchemy.iam.aggregates.identity import Identity
from etlalchemy.iam.aggregates.session import Session
from etlalchemy.iam.aggregates.tenant import Tenant
from etlalchemy.iam.aggregates.user import User
from etlalchemy.iam.projection.sqlalchemy import SQLAlchemyIamView
from etlalchemy.iam.projection.view import AuditEntry, IamView
from etlalchemy.shared.logging import get_logger
from etlalchemy.shared.projection import AsyncLoggedProjection


class IamProjectionError(RuntimeError):
    """Raised when the view cannot be updated from an IAM event."""


class IamEventApplication(AsyncApplication[UUID]):
    """Application used by the projection runner to subscribe to IAM events.

    :class:`~etlalchemy.iam.application.IamApplication` needs the read model, the
    password hasher, the secret resolver and the authorizer, so the projection
    runner cannot construct it from an environment alone. This subclass carries
    the same application name, and therefore the same event store tables.
    """

    name = "iam_application"
    """Application name; must match :class:`IamApplication`."""


def _audit(
    event: Any,
    action: str,
    target_type: str,
    target_id: str | UUID,
    *,
    tenant_id: UUID | None = None,
    detail: dict[str, Any] | None = None,
) -> AuditEntry:
    """Builds the audit entry of one structural event."""
    return AuditEntry(
        occurred_at=event.timestamp,
        action=action,
        target_type=target_type,
        target_id=str(target_id),
        tenant_id=tenant_id,
        detail={} if detail is None else detail,
    )


class IamProjection(AsyncLoggedProjection[IamView]):
    """Materialises the IAM read model from the IAM events."""

    name = "iam_projection"
    """Projection name; used as the environment prefix and tracking table prefix."""

    logger_name = "iam.projection"
    """Logger used for the per-event trail and for projection failures."""

    topics = (
        get_topic(Tenant.Started),
        get_topic(Tenant.Changed),
        get_topic(Tenant.MemberAdded),
        get_topic(Tenant.MemberRemoved),
        get_topic(Tenant.MemberStatusChanged),
        get_topic(Tenant.Discarded),
        get_topic(User.Started),
        get_topic(User.Changed),
        get_topic(User.TenantJoined),
        get_topic(User.TenantLeft),
        get_topic(User.SystemAdminGranted),
        get_topic(User.SystemAdminRevoked),
        get_topic(User.Discarded),
        get_topic(Identity.Started),
        get_topic(Identity.Changed),
        get_topic(Identity.PasswordChanged),
        get_topic(Identity.OidcSubjectLinked),
        get_topic(Identity.ApiKeyCreated),
        get_topic(Identity.ApiKeyRotated),
        get_topic(Identity.ApiKeyRevoked),
        get_topic(Identity.Discarded),
        get_topic(Session.Started),
        get_topic(Session.Refreshed),
        get_topic(Session.Revoked),
        get_topic(Session.AccessDenied),
        get_topic(Group.Started),
        get_topic(Group.Changed),
        get_topic(Group.ParentChanged),
        get_topic(Group.MemberAdded),
        get_topic(Group.MemberRemoved),
        get_topic(Group.PermissionGranted),
        get_topic(Group.PermissionRevoked),
        get_topic(Group.Discarded),
        get_topic(AuthProvider.Started),
        get_topic(AuthProvider.Changed),
        get_topic(AuthProvider.ConfigUpdated),
        get_topic(AuthProvider.Discarded),
    )

    @singledispatchmethod
    async def dispatch_event(self, domain_event: Any, tracking: Tracking) -> None:
        """Ignores events that are not handled by this projection."""

    # -- tenants ------------------------------------------------------------

    @dispatch_event.register
    async def _when_tenant_started(
        self,
        event: Tenant.Started,
        tracking: Tracking,
    ) -> None:
        """Registers the tenant."""
        await self.view.register_tenant(
            event.originator_id,
            event.name,
            event.description,
            "ACTIVE",
            tracking,
            audit=_audit(event, "tenant.started", "tenant", event.originator_id),
        )

    @dispatch_event.register
    async def _when_tenant_changed(
        self,
        event: Tenant.Changed,
        tracking: Tracking,
    ) -> None:
        """Changes the tenant metadata."""
        await self.view.change_tenant(
            event.originator_id,
            event.name,
            event.description,
            event.status,
            tracking,
            audit=_audit(event, "tenant.changed", "tenant", event.originator_id),
        )

    @dispatch_event.register
    async def _when_tenant_member_added(
        self,
        event: Tenant.MemberAdded,
        tracking: Tracking,
    ) -> None:
        """Registers the membership."""
        await self.view.register_member(
            event.originator_id,
            event.user_id,
            event.joined_at,
            event.status,
            tracking,
        )

    @dispatch_event.register
    async def _when_tenant_member_removed(
        self,
        event: Tenant.MemberRemoved,
        tracking: Tracking,
    ) -> None:
        """Removes the membership, its rules and the sessions of that tenant."""
        await self.view.remove_member(event.originator_id, event.user_id, tracking)

    @dispatch_event.register
    async def _when_tenant_member_status_changed(
        self,
        event: Tenant.MemberStatusChanged,
        tracking: Tracking,
    ) -> None:
        """Changes the membership status."""
        await self.view.change_member_status(
            event.originator_id,
            event.user_id,
            event.status,
            tracking,
        )

    @dispatch_event.register
    async def _when_tenant_discarded(
        self,
        event: Tenant.Discarded,
        tracking: Tracking,
    ) -> None:
        """Discards the tenant and cascades to its groups, rules and sessions."""
        await self.view.discard_tenant(
            event.originator_id,
            tracking,
            audit=_audit(event, "tenant.discarded", "tenant", event.originator_id),
        )

    # -- users --------------------------------------------------------------

    @dispatch_event.register
    async def _when_user_started(
        self,
        event: User.Started,
        tracking: Tracking,
    ) -> None:
        """Registers the user."""
        await self.view.register_user(
            event.originator_id,
            event.username,
            event.email,
            event.display_name,
            "ACTIVE",
            tracking,
        )

    @dispatch_event.register
    async def _when_user_changed(
        self,
        event: User.Changed,
        tracking: Tracking,
    ) -> None:
        """Changes the user metadata."""
        await self.view.change_user(
            event.originator_id,
            event.username,
            event.email,
            event.display_name,
            event.status,
            tracking,
        )

    @dispatch_event.register
    async def _when_user_tenant_joined(
        self,
        event: User.TenantJoined,
        tracking: Tracking,
    ) -> None:
        """Registers the dual membership written by the user side."""
        await self.view.register_member(
            event.tenant_id,
            event.originator_id,
            event.joined_at,
            "ACTIVE",
            tracking,
        )

    @dispatch_event.register
    async def _when_user_tenant_left(
        self,
        event: User.TenantLeft,
        tracking: Tracking,
    ) -> None:
        """Removes the dual membership written by the user side."""
        await self.view.remove_member(event.tenant_id, event.originator_id, tracking)

    @dispatch_event.register
    async def _when_user_system_admin_granted(
        self,
        event: User.SystemAdminGranted,
        tracking: Tracking,
    ) -> None:
        """Sets the system administrator flag."""
        await self.view.set_system_admin(
            event.originator_id,
            True,
            tracking,
            audit=_audit(
                event,
                "system_admin.granted",
                "user",
                event.originator_id,
                detail={"source": event.source},
            ),
        )

    @dispatch_event.register
    async def _when_user_system_admin_revoked(
        self,
        event: User.SystemAdminRevoked,
        tracking: Tracking,
    ) -> None:
        """Clears the system administrator flag."""
        await self.view.set_system_admin(
            event.originator_id,
            False,
            tracking,
            audit=_audit(event, "system_admin.revoked", "user", event.originator_id),
        )

    @dispatch_event.register
    async def _when_user_discarded(
        self,
        event: User.Discarded,
        tracking: Tracking,
    ) -> None:
        """Discards the user and cascades to its identities, sessions and rules."""
        await self.view.discard_user(event.originator_id, tracking)

    # -- identities ---------------------------------------------------------

    @dispatch_event.register
    async def _when_identity_started(
        self,
        event: Identity.Started,
        tracking: Tracking,
    ) -> None:
        """Registers the identity."""
        await self.view.register_identity(
            event.originator_id,
            event.user_id,
            event.identity_type,
            event.provider,
            event.display_name,
            "ACTIVE",
            tracking,
        )

    @dispatch_event.register
    async def _when_identity_changed(
        self,
        event: Identity.Changed,
        tracking: Tracking,
    ) -> None:
        """Changes the identity metadata."""
        await self.view.change_identity(
            event.originator_id,
            event.display_name,
            event.status,
            tracking,
        )

    @dispatch_event.register
    async def _when_identity_password_changed(
        self,
        event: Identity.PasswordChanged,
        tracking: Tracking,
    ) -> None:
        """Stores the password hash and revokes the older sessions."""
        row = await self.view.get_identity(event.originator_id)
        if row is None:
            msg = f"Identity {event.originator_id} is missing from the IAM view"
            raise IamProjectionError(msg)
        await self.view.set_password(
            event.originator_id,
            event.password_hash,
            row.credential_version + 1,
            event.timestamp,
            tracking,
            audit=_audit(
                event,
                "identity.password_changed",
                "identity",
                event.originator_id,
                detail={"user_id": str(row.user_id)},
            ),
        )

    @dispatch_event.register
    async def _when_identity_oidc_subject_linked(
        self,
        event: Identity.OidcSubjectLinked,
        tracking: Tracking,
    ) -> None:
        """Stores the OIDC binding and revokes the older sessions."""
        row = await self.view.get_identity(event.originator_id)
        if row is None:
            msg = f"Identity {event.originator_id} is missing from the IAM view"
            raise IamProjectionError(msg)
        await self.view.set_oidc_subject(
            event.originator_id,
            event.provider_id,
            event.issuer,
            event.subject,
            row.credential_version + 1,
            tracking,
            audit=_audit(
                event,
                "identity.oidc_linked",
                "identity",
                event.originator_id,
                detail={"issuer": event.issuer},
            ),
        )

    @dispatch_event.register
    async def _when_api_key_created(
        self,
        event: Identity.ApiKeyCreated,
        tracking: Tracking,
    ) -> None:
        """Registers the API key."""
        identity = await self.view.get_identity(event.originator_id)
        if identity is None:
            msg = f"Identity {event.originator_id} is missing from the IAM view"
            raise IamProjectionError(msg)
        await self.view.register_api_key(
            event.key_id,
            identity.identity_id,
            identity.user_id,
            event.prefix,
            event.secret_hash,
            list(event.scopes),
            event.created_at,
            event.expires_at,
            event.rotated_from,
            tracking,
            audit=_audit(
                event,
                "api_key.created",
                "api_key",
                event.key_id,
                detail={"user_id": str(identity.user_id)},
            ),
        )

    @dispatch_event.register
    async def _when_api_key_rotated(
        self,
        event: Identity.ApiKeyRotated,
        tracking: Tracking,
    ) -> None:
        """Moves the old key into grace and registers the replacement."""
        old_key = await self.view.get_api_key(event.old_key_id)
        if old_key is None:
            msg = f"API key {event.old_key_id} is missing from the IAM view"
            raise IamProjectionError(msg)
        await self.view.rotate_api_key(
            event.old_key_id,
            event.new_key_id,
            old_key.identity_id,
            old_key.user_id,
            event.new_prefix,
            event.new_secret_hash,
            old_key.scopes,
            event.created_at or event.timestamp,
            old_key.expires_at,
            event.grace_until,
            tracking,
            audit=_audit(
                event,
                "api_key.rotated",
                "api_key",
                event.new_key_id,
                detail={"rotated_from": str(event.old_key_id)},
            ),
        )

    @dispatch_event.register
    async def _when_api_key_revoked(
        self,
        event: Identity.ApiKeyRevoked,
        tracking: Tracking,
    ) -> None:
        """Revokes the API key and its sessions."""
        await self.view.revoke_api_key(
            event.key_id,
            event.revoked_at,
            tracking,
            audit=_audit(event, "api_key.revoked", "api_key", event.key_id),
        )

    @dispatch_event.register
    async def _when_identity_discarded(
        self,
        event: Identity.Discarded,
        tracking: Tracking,
    ) -> None:
        """Discards the identity, its credentials, keys and sessions."""
        await self.view.discard_identity(
            event.originator_id,
            tracking,
            audit=_audit(event, "identity.discarded", "identity", event.originator_id),
        )

    # -- sessions -----------------------------------------------------------

    @dispatch_event.register
    async def _when_session_started(
        self,
        event: Session.Started,
        tracking: Tracking,
    ) -> None:
        """Registers the session."""
        await self.view.register_session(
            event.originator_id,
            event.identity_id,
            event.user_id,
            event.tenant_id,
            event.identity_type,
            event.api_key_id,
            event.credential_version,
            event.timestamp,
            event.expires_at,
            tracking,
        )

    @dispatch_event.register
    async def _when_session_refreshed(
        self,
        event: Session.Refreshed,
        tracking: Tracking,
    ) -> None:
        """Updates the expiry of the session."""
        await self.view.refresh_session(
            event.originator_id,
            event.expires_at,
            event.last_seen_at,
            tracking,
        )

    @dispatch_event.register
    async def _when_session_revoked(
        self,
        event: Session.Revoked,
        tracking: Tracking,
    ) -> None:
        """Marks the session as revoked and audits non-logout reasons."""
        audit = None
        if event.reason != "logout":
            audit = _audit(
                event,
                "session.revoked",
                "session",
                event.originator_id,
                detail={"reason": event.reason},
            )
        await self.view.revoke_session(event.originator_id, event.reason, tracking, audit=audit)

    @dispatch_event.register
    async def _when_session_access_denied(
        self,
        event: Session.AccessDenied,
        tracking: Tracking,
    ) -> None:
        """Records the denied authorization in the audit log."""
        await self.view.add_audit(
            AuditEntry(
                occurred_at=event.timestamp,
                action="authorize.denied",
                target_type="permission",
                target_id=f"{event.obj}:{event.act}",
                result="denied",
                actor_user_id=event.actor_user_id,
                actor_identity_id=event.actor_identity_id,
                detail={
                    "session_id": str(event.originator_id),
                    "obj": event.obj,
                    "act": event.act,
                    "reason": event.reason,
                },
            ),
            tracking,
        )

    # -- groups -------------------------------------------------------------

    @dispatch_event.register
    async def _when_group_started(
        self,
        event: Group.Started,
        tracking: Tracking,
    ) -> None:
        """Registers the group."""
        await self.view.register_group(
            event.originator_id,
            event.tenant_id,
            event.name,
            event.description,
            event.parent_group_id,
            tracking,
        )

    @dispatch_event.register
    async def _when_group_changed(
        self,
        event: Group.Changed,
        tracking: Tracking,
    ) -> None:
        """Changes the group metadata."""
        await self.view.change_group(
            event.originator_id,
            event.name,
            event.description,
            tracking,
        )

    @dispatch_event.register
    async def _when_group_parent_changed(
        self,
        event: Group.ParentChanged,
        tracking: Tracking,
    ) -> None:
        """Moves the group below its new parent."""
        await self.view.change_group_parent(
            event.originator_id,
            event.new_parent_id,
            tracking,
        )

    @dispatch_event.register
    async def _when_group_member_added(
        self,
        event: Group.MemberAdded,
        tracking: Tracking,
    ) -> None:
        """Adds the member and writes its Casbin rule."""
        group = await self._group(event.originator_id)
        await self.view.add_group_member(
            event.originator_id,
            event.member_id,
            event.member_kind,
            group.tenant_id,
            event.added_at,
            tracking,
        )

    @dispatch_event.register
    async def _when_group_member_removed(
        self,
        event: Group.MemberRemoved,
        tracking: Tracking,
    ) -> None:
        """Removes the member and deletes its Casbin rule."""
        await self.view.remove_group_member(
            event.originator_id,
            event.member_id,
            event.member_kind,
            tracking,
        )

    @dispatch_event.register
    async def _when_group_permission_granted(
        self,
        event: Group.PermissionGranted,
        tracking: Tracking,
    ) -> None:
        """Registers the grant and writes its Casbin rule."""
        group = await self._group(event.originator_id)
        await self.view.grant_permission(
            event.originator_id,
            group.tenant_id,
            event.obj,
            event.act,
            tracking,
        )

    @dispatch_event.register
    async def _when_group_permission_revoked(
        self,
        event: Group.PermissionRevoked,
        tracking: Tracking,
    ) -> None:
        """Removes the grant and deletes its Casbin rule."""
        group = await self._group(event.originator_id)
        await self.view.revoke_permission(
            event.originator_id,
            group.tenant_id,
            event.obj,
            event.act,
            tracking,
        )

    @dispatch_event.register
    async def _when_group_discarded(
        self,
        event: Group.Discarded,
        tracking: Tracking,
    ) -> None:
        """Discards the group together with its members, grants and rules."""
        await self.view.discard_groups(
            [event.originator_id],
            tracking,
        )

    # -- auth providers -----------------------------------------------------

    @dispatch_event.register
    async def _when_provider_started(
        self,
        event: AuthProvider.Started,
        tracking: Tracking,
    ) -> None:
        """Registers the auth provider."""
        await self.view.register_provider(
            event.originator_id,
            event.provider_key,
            event.kind,
            event.display_name,
            event.tenant_id,
            event.config,
            "ENABLED",
            tracking,
            audit=_audit(
                event,
                "auth_provider.started",
                "auth_provider",
                event.originator_id,
                detail={"provider_key": event.provider_key},
            ),
        )

    @dispatch_event.register
    async def _when_provider_changed(
        self,
        event: AuthProvider.Changed,
        tracking: Tracking,
    ) -> None:
        """Changes the auth provider metadata."""
        await self.view.change_provider(
            event.originator_id,
            event.display_name,
            event.status,
            tracking,
            audit=_audit(
                event,
                "auth_provider.changed",
                "auth_provider",
                event.originator_id,
                detail={"status": event.status},
            ),
        )

    @dispatch_event.register
    async def _when_provider_config_updated(
        self,
        event: AuthProvider.ConfigUpdated,
        tracking: Tracking,
    ) -> None:
        """Replaces the auth provider configuration."""
        await self.view.update_provider_config(
            event.originator_id,
            event.config,
            tracking,
            audit=_audit(
                event,
                "auth_provider.config_updated",
                "auth_provider",
                event.originator_id,
            ),
        )

    @dispatch_event.register
    async def _when_provider_discarded(
        self,
        event: AuthProvider.Discarded,
        tracking: Tracking,
    ) -> None:
        """Discards the auth provider."""
        await self.view.discard_provider(
            event.originator_id,
            tracking,
            audit=_audit(
                event,
                "auth_provider.discarded",
                "auth_provider",
                event.originator_id,
            ),
        )

    async def _group(self, group_id: UUID) -> Any:
        """Returns the group row, raising when the view lost it."""
        group = await self.view.get_group(group_id)
        if group is None:
            msg = f"Group {group_id} is missing from the IAM view"
            raise IamProjectionError(msg)
        return group


def run_iam_projection(
    env: EnvType | None = None,
) -> AsyncProjectionRunner[IamEventApplication, IamView]:
    """Builds a runner that keeps the IAM view up to date.

    The runner is not started yet: the caller awaits ``start()`` (or uses the
    runner as an async context manager).
    """
    runner = AsyncProjectionRunner[IamEventApplication, IamView](
        application_class=IamEventApplication,
        projection_class=IamProjection,
        view_class=SQLAlchemyIamView,
        env=env,
    )
    get_logger(IamProjection.logger_name).info(
        "projection.runner.started",
        application=IamEventApplication.name,
        projection=IamProjection.name,
        view=SQLAlchemyIamView.__name__,
    )
    return runner
