"""OIDC use-case tests: binding, authentication, refresh and provider lifecycle."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from etlalchemy.iam.aggregates.errors import (
    IdentityUnavailableError,
    IamValidationError,
    UnknownAuthProviderError,
    UnknownMembershipError,
)
from etlalchemy.iam.application import IamApplication, IamOptions, SessionRef
from etlalchemy.iam.projection.projection import run_iam_projection
from tests.iam.support import build_application, login, sync
from tests.support import async_env, sqlite_url

PASSWORD = "correct-horse-battery"
ADMIN = "root@example.com"
SECRET = "s3cr3t-client-secret"


def oidc_config(
    issuer: str = "https://idp.example",
    redirect_uri: str = "https://app.example/oidc/callback",
    secret_ref: str = "env:OIDC_SECRET",
    client_id: str = "etlalchemy",
) -> dict[str, str]:
    """Returns a valid OIDC provider configuration."""
    base = issuer.rstrip("/")
    return {
        "issuer": issuer,
        "authorization_endpoint": f"{base}/authorize",
        "token_endpoint": f"{base}/token",
        "jwks_uri": f"{base}/jwks",
        "client_id": client_id,
        "client_secret_ref": secret_ref,
        "userinfo_endpoint": "",
        "scopes": "openid email",
        "redirect_uris": redirect_uri,
    }


@pytest.fixture
def env(tmp_path: Path) -> dict[str, str]:
    """Returns an environment backed by a temporary SQLite event store."""
    return async_env(sqlite_url(tmp_path / "events.db"))


@pytest.fixture
async def iam(
    env: dict[str, str],
) -> AsyncIterator[tuple[IamApplication, Any]]:
    """Returns a started application whose OIDC sessions live one hour."""
    options = IamOptions(
        password_min_length=8,
        api_key_pepper="test-pepper",
        oidc_session_minutes=60,
        password_session_minutes=600,
    )
    async with run_iam_projection(env) as runner:
        application = build_application(env, runner.view, options)
        async with application:
            await application.bootstrap_admin(ADMIN, PASSWORD)
            await sync(runner, application)
            yield application, runner


async def provider_id(application: IamApplication, runner: Any, tenant_id: Any = None) -> Any:
    """Creates an OIDC provider and returns its id."""
    created = await application.create_auth_provider(
        (await login(application, runner, ADMIN, PASSWORD)).session_id,
        "corp",
        "OIDC",
        "Corporate IdP",
        oidc_config(),
        tenant_id,
    )
    await sync(runner, application)
    return created


async def new_user(application: IamApplication, runner: Any, login_name: str) -> Any:
    """Creates a user with a password identity and returns its id."""
    session = await login(application, runner, ADMIN, PASSWORD)
    user_id = await application.create_user(
        session.session_id,
        login_name,
        f"{login_name}@example.com",
    )
    await application.create_password_identity(session.session_id, user_id, PASSWORD)
    await sync(runner, application)
    return user_id


async def bind(
    application: IamApplication,
    runner: Any,
    user_id: Any,
    provider: Any,
    subject: str = "subject-1",
) -> Any:
    """Binds a subject to the user through the OIDC identity use case."""
    session = await login(application, runner, ADMIN, PASSWORD)
    identity_id = await application.create_oidc_identity(
        session.session_id,
        user_id,
        provider,
        subject,
    )
    await sync(runner, application)
    return identity_id


async def test_binding_and_authentication_issue_an_oidc_session(
    iam: tuple[IamApplication, Any],
) -> None:
    """A pre-bound subject authenticates and gets an OIDC session."""
    application, runner = iam
    provider = await provider_id(application, runner)
    user_id = await new_user(application, runner, "alice")
    await bind(application, runner, user_id, provider)

    session = await application.authenticate_oidc("https://idp.example", "subject-1")
    assert isinstance(session, SessionRef)
    assert session.user_id == user_id
    await sync(runner, application)

    unknown = await application.authenticate_oidc("https://idp.example", "nobody")
    assert not isinstance(unknown, SessionRef)
    assert unknown.subject == "nobody"


async def test_refresh_keeps_the_oidc_session_lifetime(
    iam: tuple[IamApplication, Any],
) -> None:
    """Refreshing an OIDC session uses the OIDC TTL, not the password TTL."""
    application, runner = iam
    provider = await provider_id(application, runner)
    user_id = await new_user(application, runner, "alice")
    await bind(application, runner, user_id, provider)
    session = await application.authenticate_oidc("https://idp.example", "subject-1")
    assert isinstance(session, SessionRef)
    await sync(runner, application)

    refreshed = await application.refresh_session(session.session_id)
    remaining = refreshed.expires_at - datetime.now(UTC)
    assert timedelta(minutes=55) < remaining <= timedelta(minutes=61)


async def test_tenant_scoped_provider_only_serves_its_tenant(
    iam: tuple[IamApplication, Any],
) -> None:
    """A tenant-scoped provider rejects users outside that tenant."""
    application, runner = iam
    admin_session = await login(application, runner, ADMIN, PASSWORD)
    tenant_id = await application.create_tenant(admin_session.session_id, "acme")
    await sync(runner, application)
    provider = await provider_id(application, runner, tenant_id)
    user_id = await new_user(application, runner, "alice")

    with pytest.raises(UnknownMembershipError):
        await bind(application, runner, user_id, provider)

    await application.add_tenant_member(admin_session.session_id, tenant_id, user_id)
    await sync(runner, application)
    await bind(application, runner, user_id, provider)

    with pytest.raises(IdentityUnavailableError):
        await application.authenticate_oidc("https://idp.example", "subject-1")

    session = await application.authenticate_oidc(
        "https://idp.example",
        "subject-1",
        tenant_id,
    )
    assert isinstance(session, SessionRef)
    assert session.tenant_id == tenant_id


async def test_discarded_provider_cannot_gain_bindings(
    iam: tuple[IamApplication, Any],
) -> None:
    """A discarded provider is rejected even though its status still reads ENABLED."""
    application, runner = iam
    provider = await provider_id(application, runner)
    user_id = await new_user(application, runner, "alice")
    admin_session = await login(application, runner, ADMIN, PASSWORD)

    await application.discard_auth_provider(admin_session.session_id, provider)
    await sync(runner, application)

    with pytest.raises(UnknownAuthProviderError):
        await bind(application, runner, user_id, provider)


async def test_the_issuer_cannot_change_while_identities_are_bound(
    iam: tuple[IamApplication, Any],
) -> None:
    """Changing the issuer would orphan bindings, so it is rejected."""
    application, runner = iam
    provider = await provider_id(application, runner)
    user_id = await new_user(application, runner, "alice")
    await bind(application, runner, user_id, provider)
    admin_session = await login(application, runner, ADMIN, PASSWORD)

    with pytest.raises(IamValidationError):
        await application.update_auth_provider_config(
            admin_session.session_id,
            provider,
            oidc_config(issuer="https://other-idp.example"),
        )

    updated = oidc_config(client_id="etlalchemy-v2")
    await application.update_auth_provider_config(
        admin_session.session_id,
        provider,
        updated,
    )


async def test_provider_client_secret_is_resolved_per_call(
    iam: tuple[IamApplication, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The host adapter reads the client secret from the secret store."""
    application, runner = iam
    provider = await provider_id(application, runner)

    monkeypatch.setenv("OIDC_SECRET", SECRET)
    assert await application.provider_client_secret(provider) == SECRET

    monkeypatch.delenv("OIDC_SECRET")
    with pytest.raises(IamValidationError):
        await application.provider_client_secret(provider)

    with pytest.raises(UnknownAuthProviderError):
        await application.provider_client_secret(uuid4())
