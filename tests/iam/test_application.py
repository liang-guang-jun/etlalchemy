"""End-to-end tests of the IAM use cases against the SQLite read model."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from etlalchemy.iam.aggregates.errors import (
    AuthenticationError,
    BootstrapAlreadyCompletedError,
    DuplicateGroupError,
    DuplicateIdentityError,
    GroupCycleError,
    IdentityInvariantError,
    LastSystemAdminError,
    LastLoginIdentityError,
    PermissionDeniedError,
    ScopeExceedsGrantError,
    SessionRevokedError,
)
from etlalchemy.iam.application import IamApplication
from etlalchemy.iam.projection.projection import run_iam_projection
from tests.iam.support import build_application, login, login_api_key, sync
from tests.support import async_env, sqlite_url

PASSWORD = "correct-horse-battery"


@pytest.fixture
def env(tmp_path: Path) -> dict[str, str]:
    """Returns an environment backed by a temporary SQLite event store."""
    return async_env(sqlite_url(tmp_path / "events.db"))


@pytest.fixture
async def iam(env: dict[str, str]) -> AsyncIterator[tuple[IamApplication, Any]]:
    """Returns a started IAM application and its runner."""
    async with run_iam_projection(env) as runner:
        application = build_application(env, runner.view)
        async with application:
            yield application, runner


async def bootstrap(application: IamApplication, runner: Any) -> Any:
    """Creates the first system administrator and logs it in."""
    await application.bootstrap_admin("root@example.com", PASSWORD)
    await sync(runner, application)
    return await login(application, runner, "root@example.com", PASSWORD)


async def make_tenant(application: IamApplication, runner: Any, session: Any, name: str) -> Any:
    """Creates a tenant and returns its id."""
    tenant_id = await application.create_tenant(session.session_id, name)
    await sync(runner, application)
    return tenant_id


async def make_user(
    application: IamApplication,
    runner: Any,
    session: Any,
    login: str,
) -> Any:
    """Creates a user with a password identity and returns its id."""
    user_id = await application.create_user(session.session_id, login, f"{login}@example.com")
    await application.create_password_identity(session.session_id, user_id, PASSWORD)
    await sync(runner, application)
    return user_id


async def test_bootstrap_is_only_possible_once(iam: tuple[IamApplication, Any]) -> None:
    """The first bootstrap succeeds, the second is rejected."""
    application, runner = iam
    assert await application.bootstrap_status() is False

    await application.bootstrap_admin("root@example.com", PASSWORD)
    await sync(runner, application)

    assert await application.bootstrap_status() is True
    with pytest.raises(BootstrapAlreadyCompletedError):
        await application.bootstrap_admin("other@example.com", PASSWORD)

    admins = await application.list_system_admins()
    assert [admin.email for admin in admins] == ["root@example.com"]


async def test_password_authentication_and_wrong_password(
    iam: tuple[IamApplication, Any],
) -> None:
    """A correct password issues a session and a wrong one is rejected."""
    application, runner = iam
    await application.bootstrap_admin("root@example.com", PASSWORD)
    await sync(runner, application)

    session = await login(application, runner, "root@example.com", PASSWORD)
    assert session.user_id is not None
    assert session.expires_at > datetime.now(UTC)

    with pytest.raises(AuthenticationError):
        await application.authenticate_password("root@example.com", "wrong-password")
    with pytest.raises(AuthenticationError):
        await application.authenticate_password("missing@example.com", PASSWORD)


async def test_tenant_membership_is_written_on_both_sides(
    iam: tuple[IamApplication, Any],
) -> None:
    """Adding a member writes the tenant and the user stream in one unit of work."""
    application, runner = iam
    root = await bootstrap(application, runner)
    tenant_id = await make_tenant(application, runner, root, "acme")
    user_id = await make_user(application, runner, root, "alice")

    await application.add_tenant_member(root.session_id, tenant_id, user_id)
    await sync(runner, application)

    members = await application.list_tenant_members(root.session_id, tenant_id)
    assert [member.username for member in members] == ["alice"]

    tenant = await application._tenant(tenant_id)  # noqa: SLF001 - assertion helper
    user = await application._user(user_id)  # noqa: SLF001 - assertion helper
    assert tenant.has_member(user_id)
    assert tenant_id in user.memberships


async def test_group_permissions_are_inherited_through_nesting(
    iam: tuple[IamApplication, Any],
) -> None:
    """A member of a child group inherits the grants of its ancestors."""
    application, runner = iam
    root = await bootstrap(application, runner)
    tenant_id = await make_tenant(application, runner, root, "acme")
    user_id = await make_user(application, runner, root, "alice")
    await application.add_tenant_member(root.session_id, tenant_id, user_id)

    parent_id = await application.create_group(root.session_id, tenant_id, "analysts")
    child_id = await application.create_group(
        root.session_id,
        tenant_id,
        "reporting",
        parent_id,
    )
    await application.grant_group_permission(
        root.session_id,
        tenant_id,
        parent_id,
        "doc",
        "read",
    )
    await application.add_group_member(root.session_id, child_id, user_id)
    await sync(runner, application)

    session = await login(application, runner, "alice", PASSWORD, tenant_id)
    assert await application.authorize(session.session_id, "doc", "read") is True
    assert await application.authorize(session.session_id, "doc", "write") is False

    permissions = await application.effective_permissions(session.session_id)
    assert "doc:read" in {str(permission) for permission in permissions}


async def test_moving_a_group_into_its_own_subtree_is_rejected(
    iam: tuple[IamApplication, Any],
) -> None:
    """A cycle in the group tree is refused before anything is written."""
    application, runner = iam
    root = await bootstrap(application, runner)
    tenant_id = await make_tenant(application, runner, root, "acme")
    parent_id = await application.create_group(root.session_id, tenant_id, "analysts")
    child_id = await application.create_group(
        root.session_id,
        tenant_id,
        "reporting",
        parent_id,
    )
    await sync(runner, application)

    with pytest.raises(GroupCycleError):
        await application.set_group_parent(root.session_id, parent_id, child_id)


async def test_sibling_group_names_are_unique(
    iam: tuple[IamApplication, Any],
) -> None:
    """Two groups below the same parent cannot share a name."""
    application, runner = iam
    root = await bootstrap(application, runner)
    tenant_id = await make_tenant(application, runner, root, "acme")
    await application.create_group(root.session_id, tenant_id, "analysts")
    await sync(runner, application)

    with pytest.raises(DuplicateGroupError):
        await application.create_group(root.session_id, tenant_id, "analysts")


async def test_changing_a_password_invalidates_the_old_session(
    iam: tuple[IamApplication, Any],
) -> None:
    """The credential version check denies the old session immediately."""
    application, runner = iam
    root = await bootstrap(application, runner)
    user_id = await make_user(application, runner, root, "alice")
    session = await login(application, runner, "alice", PASSWORD)

    await application.change_own_password(session.session_id, PASSWORD, "new-password-123")
    await sync(runner, application)

    assert await application.authorize(session.session_id, "doc", "read") is False
    refreshed = await login(application, runner, "alice", "new-password-123")
    assert refreshed.user_id == user_id


async def test_api_key_lifecycle_and_scope_trimming(
    iam: tuple[IamApplication, Any],
) -> None:
    """API keys authenticate, rotate into grace, and are cut down by their scopes."""
    application, runner = iam
    root = await bootstrap(application, runner)
    tenant_id = await make_tenant(application, runner, root, "acme")
    user_id = await make_user(application, runner, root, "alice")
    await application.add_tenant_member(root.session_id, tenant_id, user_id)
    group_id = await application.create_group(root.session_id, tenant_id, "analysts")
    await application.grant_group_permission(
        root.session_id,
        tenant_id,
        group_id,
        "doc",
        "read",
    )
    await application.add_group_member(root.session_id, group_id, user_id)
    await sync(runner, application)

    user_session = await login(application, runner, "alice", PASSWORD, tenant_id)
    created = await application.create_api_key(
        user_session.session_id,
        user_id,
        ["doc:read"],
    )
    await sync(runner, application)

    api_session = await login_api_key(application, runner, created.secret)
    assert api_session.user_id == user_id
    assert await application.authorize(api_session.session_id, "doc", "read") is True
    assert await application.authorize(api_session.session_id, "doc", "write") is False

    rotated = await application.rotate_api_key(
        user_session.session_id,
        user_id,
        created.key_id,
        timedelta(days=1),
    )
    await sync(runner, application)
    in_grace = await login_api_key(application, runner, created.secret)
    assert in_grace.user_id == user_id

    await application.revoke_api_key(user_session.session_id, user_id, rotated.key_id)
    await sync(runner, application)
    with pytest.raises(AuthenticationError):
        await application.authenticate_api_key(rotated.secret)


async def test_scopes_cannot_exceed_the_granted_permissions(
    iam: tuple[IamApplication, Any],
) -> None:
    """A key may not ask for a permission the user does not hold."""
    application, runner = iam
    root = await bootstrap(application, runner)
    tenant_id = await make_tenant(application, runner, root, "acme")
    user_id = await make_user(application, runner, root, "alice")
    await application.add_tenant_member(root.session_id, tenant_id, user_id)
    await sync(runner, application)

    session = await login(application, runner, "alice", PASSWORD, tenant_id)
    with pytest.raises(ScopeExceedsGrantError):
        await application.create_api_key(session.session_id, user_id, ["doc:write"])


async def test_removing_a_member_revokes_sessions_and_rules(
    iam: tuple[IamApplication, Any],
) -> None:
    """Removing a membership invalidates the tenant sessions of that user."""
    application, runner = iam
    root = await bootstrap(application, runner)
    tenant_id = await make_tenant(application, runner, root, "acme")
    user_id = await make_user(application, runner, root, "alice")
    await application.add_tenant_member(root.session_id, tenant_id, user_id)
    group_id = await application.create_group(root.session_id, tenant_id, "analysts")
    await application.grant_group_permission(
        root.session_id,
        tenant_id,
        group_id,
        "doc",
        "read",
    )
    await application.add_group_member(root.session_id, group_id, user_id)
    await sync(runner, application)
    session = await login(application, runner, "alice", PASSWORD, tenant_id)
    assert await application.authorize(session.session_id, "doc", "read") is True

    await application.remove_tenant_member(root.session_id, tenant_id, user_id)
    await sync(runner, application)

    assert await application.authorize(session.session_id, "doc", "read") is False


async def test_last_system_admin_cannot_be_revoked(
    iam: tuple[IamApplication, Any],
) -> None:
    """The last system administrator is protected."""
    application, runner = iam
    root = await bootstrap(application, runner)

    with pytest.raises(LastSystemAdminError):
        await application.revoke_system_admin(root.session_id, root.user_id)


async def test_system_admin_grants_need_a_password_identity(
    iam: tuple[IamApplication, Any],
) -> None:
    """A user without a password identity cannot be promoted."""
    application, runner = iam
    root = await bootstrap(application, runner)
    user_id = await application.create_user(root.session_id, "bob", "bob@example.com")
    await sync(runner, application)

    with pytest.raises(IdentityInvariantError):
        await application.grant_system_admin(root.session_id, user_id)


async def test_password_identity_is_unique_per_user(
    iam: tuple[IamApplication, Any],
) -> None:
    """A user cannot have two password identities."""
    application, runner = iam
    root = await bootstrap(application, runner)
    user_id = await make_user(application, runner, root, "alice")

    with pytest.raises(DuplicateIdentityError):
        await application.create_password_identity(root.session_id, user_id, PASSWORD)


async def test_the_last_login_identity_cannot_be_removed(
    iam: tuple[IamApplication, Any],
) -> None:
    """A user is never locked out by removing its last login identity."""
    application, runner = iam
    root = await bootstrap(application, runner)
    user_id = await make_user(application, runner, root, "alice")
    await sync(runner, application)
    identities = await application.list_identities(root.session_id, user_id)

    with pytest.raises(LastLoginIdentityError):
        await application.discard_identity(root.session_id, identities[0].identity_id)


async def test_denied_authorization_is_audited(iam: tuple[IamApplication, Any]) -> None:
    """A denied check is recorded in the audit log."""
    application, runner = iam
    root = await bootstrap(application, runner)
    tenant_id = await make_tenant(application, runner, root, "acme")
    user_id = await make_user(application, runner, root, "alice")
    await application.add_tenant_member(root.session_id, tenant_id, user_id)
    await sync(runner, application)
    session = await login(application, runner, "alice", PASSWORD, tenant_id)

    assert await application.authorize(session.session_id, "doc", "read") is False
    await sync(runner, application)

    audit = await application.list_audit_events(root.session_id, action="authorize.denied")
    assert audit[0].result == "denied"
    assert audit[0].actor_user_id == user_id


async def test_non_admin_cannot_create_a_tenant(iam: tuple[IamApplication, Any]) -> None:
    """Tenant management is reserved to system administrators."""
    application, runner = iam
    root = await bootstrap(application, runner)
    tenant_id = await make_tenant(application, runner, root, "acme")
    user_id = await make_user(application, runner, root, "alice")
    await application.add_tenant_member(root.session_id, tenant_id, user_id)
    await sync(runner, application)
    session = await login(application, runner, "alice", PASSWORD, tenant_id)

    with pytest.raises(PermissionDeniedError):
        await application.create_tenant(session.session_id, "other")


async def test_unknown_session_is_denied(iam: tuple[IamApplication, Any]) -> None:
    """An unknown session id never authorizes anything."""
    application, _runner = iam
    assert await application.authorize(uuid4(), "doc", "read") is False


async def test_validate_session_reports_the_caller_and_the_admin_flag(
    iam: tuple[IamApplication, Any],
) -> None:
    """A valid session resolves to its user and the system administrator flag."""
    application, runner = iam
    root = await bootstrap(application, runner)

    validated_root = await application.validate_session(root.session_id)

    assert validated_root.session_id == root.session_id
    assert validated_root.user_id == root.user_id
    assert validated_root.is_system_admin is True

    await make_user(application, runner, root, "alice")
    alice_session = await login(application, runner, "alice", PASSWORD)

    validated_alice = await application.validate_session(alice_session.session_id)

    assert validated_alice.is_system_admin is False


async def test_validate_session_rejects_an_unknown_session(
    iam: tuple[IamApplication, Any],
) -> None:
    """An unknown session id is an authentication failure."""
    application, _runner = iam

    with pytest.raises(AuthenticationError):
        await application.validate_session(uuid4())


async def test_validate_session_rejects_a_revoked_session(
    iam: tuple[IamApplication, Any],
) -> None:
    """A revoked session is no longer usable for authentication."""
    application, runner = iam
    root = await bootstrap(application, runner)
    await application.revoke_session(root.session_id)
    await sync(runner, application)

    with pytest.raises(SessionRevokedError):
        await application.validate_session(root.session_id)


async def test_validate_session_rejects_a_suspended_user(
    iam: tuple[IamApplication, Any],
) -> None:
    """A suspended user invalidates the sessions of its identities."""
    application, runner = iam
    root = await bootstrap(application, runner)
    user_id = await make_user(application, runner, root, "alice")
    session = await login(application, runner, "alice", PASSWORD)

    await application.change_user(root.session_id, user_id, status="SUSPENDED")
    await sync(runner, application)

    with pytest.raises((AuthenticationError, SessionRevokedError)):
        await application.validate_session(session.session_id)


async def test_validate_session_rejects_a_stale_credential(
    iam: tuple[IamApplication, Any],
) -> None:
    """A password change invalidates sessions issued with the old version."""
    application, runner = iam
    root = await bootstrap(application, runner)
    await make_user(application, runner, root, "alice")
    session = await login(application, runner, "alice", PASSWORD)

    await application.change_own_password(session.session_id, PASSWORD, "new-password-123")
    await sync(runner, application)

    with pytest.raises((AuthenticationError, SessionRevokedError)):
        await application.validate_session(session.session_id)


async def test_validated_session_expiries_are_timezone_aware(
    iam: tuple[IamApplication, Any],
) -> None:
    """SQLite returns naive datetimes, so the use cases normalise them to UTC."""
    application, runner = iam
    root = await bootstrap(application, runner)

    validated = await application.validate_session(root.session_id)
    current = await application.get_session(root.session_id)

    assert validated.expires_at.tzinfo is not None
    assert current.expires_at.tzinfo is not None
