"""``etla iam``: command line administration of the IAM context.

Every command goes through :class:`IamApplication`; nothing touches the event
tables directly. Passwords are only ever read from a hidden TTY prompt.
"""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar
from uuid import UUID

import typer

from etlalchemy.app.bootstrap import Container, run_container
from etlalchemy.iam.aggregates.errors import (
    AuthenticationError,
    IamError,
    PermissionDeniedError,
    SessionExpiredError,
    SessionRevokedError,
    UnknownAuthProviderError,
    UnknownTenantError,
    UnknownUserError,
)
from etlalchemy.iam.application import IamApplication

iam_app = typer.Typer(
    name="iam",
    help="Identity and access management.",
    no_args_is_help=True,
)
bootstrap_app = typer.Typer(
    name="bootstrap", help="First system administrator.", no_args_is_help=True
)
admin_app = typer.Typer(name="admin", help="Administrator accounts.", no_args_is_help=True)
tenant_app = typer.Typer(name="tenant", help="Tenants and members.", no_args_is_help=True)
provider_app = typer.Typer(name="provider", help="Auth providers.", no_args_is_help=True)
self_app = typer.Typer(name="self", help="Self service.", no_args_is_help=True)

iam_app.add_typer(bootstrap_app, name="bootstrap")
iam_app.add_typer(admin_app, name="admin")
iam_app.add_typer(tenant_app, name="tenant")
iam_app.add_typer(provider_app, name="provider")
iam_app.add_typer(self_app, name="self")

T = TypeVar("T")
"""Result type of a use case run by :func:`_execute`."""

UNAUTHORIZED = (
    AuthenticationError,
    PermissionDeniedError,
    SessionExpiredError,
    SessionRevokedError,
)


def _session_id(explicit: str | None) -> UUID:
    """Returns the session id from ``--session`` or ``IAM_SESSION``."""
    value = explicit or os.environ.get("IAM_SESSION")
    if not value:
        typer.echo("a session is required: run 'etla iam login' or pass --session", err=True)
        raise typer.Exit(3)
    try:
        return UUID(value)
    except ValueError:
        typer.echo(f"invalid session id: {value}", err=True)
        raise typer.Exit(2) from None


async def _with_application[T](action: Callable[[IamApplication], Awaitable[T]]) -> T:
    """Runs a use case inside the container lifecycle.

    The lifecycle logs at ``INFO`` for the server; a CLI command only reports its
    own result, so the process-wide level is raised to ``WARNING`` first (the
    container configures logging from these settings).
    """
    container = Container()
    settings = container.settings()
    settings.logging.level = "WARNING"
    settings.logging.color = False
    async with run_container(container):
        return await action(container.iam_application())


def _execute[T](
    action: Callable[[IamApplication], Awaitable[T]],
    *,
    as_json: bool = False,
    render: Callable[[T], Any] | None = None,
) -> None:
    """Runs a use case, maps its errors to exit codes and prints the result."""
    try:
        result = asyncio.run(_with_application(action))
    except UNAUTHORIZED as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(3) from exc
    except (UnknownTenantError, UnknownUserError, UnknownAuthProviderError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc
    except IamError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(2) from exc
    if result is None:
        return
    payload = render(result) if render is not None else result
    if as_json:
        typer.echo(json.dumps(payload, default=str, ensure_ascii=False))
    else:
        typer.echo(payload)


def _json_option() -> Any:
    """Returns the shared ``--json`` option."""
    return typer.Option(False, "--json", help="Print the result as JSON.")


def _session_option() -> Any:
    """Returns the shared ``--session`` option."""
    return typer.Option(None, "--session", help="Session id; defaults to $IAM_SESSION.")


def _password(prompt: str = "Password") -> str:
    """Reads a password from a hidden TTY prompt with confirmation."""
    return str(typer.prompt(prompt, hide_input=True, confirmation_prompt=True))


# -- bootstrap --------------------------------------------------------------


@bootstrap_app.command("status")
def bootstrap_status(as_json: bool = _json_option()) -> None:
    """Report whether a system administrator exists."""

    async def action(application: IamApplication) -> bool:
        return await application.bootstrap_status()

    _execute(
        action,
        as_json=as_json,
        render=lambda completed: (
            {"completed": completed}
            if as_json
            else ("completed" if completed else "not initialized")
        ),
    )


@bootstrap_app.command("admin")
def bootstrap_admin(
    email: str = typer.Option(..., help="Email of the first system administrator."),
    as_json: bool = _json_option(),
) -> None:
    """Create the first system administrator."""
    password = _password()

    async def action(application: IamApplication) -> UUID:
        return await application.bootstrap_admin(email, password)

    _execute(
        action,
        as_json=as_json,
        render=lambda user_id: {"user_id": str(user_id)} if as_json else str(user_id),
    )


# -- sessions ---------------------------------------------------------------


@iam_app.command("login")
def login(
    email: str = typer.Option(..., "--email", "-e", help="Login or email address."),
    tenant: str | None = typer.Option(None, "--tenant", help="Tenant name to act in."),
    as_json: bool = _json_option(),
) -> None:
    """Authenticate with a password and print the session id."""
    password = str(typer.prompt("Password", hide_input=True))

    async def action(application: IamApplication) -> str:
        tenant_id = None
        if tenant is not None:
            for row in await application.list_tenants():
                if row.name == tenant:
                    tenant_id = row.tenant_id
                    break
            if tenant_id is None:
                raise UnknownTenantError(f"tenant {tenant!r} does not exist")
        session = await application.authenticate_password(email, password, tenant_id)
        return str(session.session_id)

    _execute(
        action,
        as_json=as_json,
        render=lambda session_id: {"session_id": session_id} if as_json else session_id,
    )


@iam_app.command("logout")
def logout(session: str | None = _session_option()) -> None:
    """Revoke the current session."""
    session_id = _session_id(session)

    async def action(application: IamApplication) -> None:
        await application.revoke_session(session_id, "logout")

    _execute(action)


# -- administration ---------------------------------------------------------


@admin_app.command("create")
def admin_create(
    email: str = typer.Option(..., "--email", "-e"),
    session: str | None = _session_option(),
    as_json: bool = _json_option(),
) -> None:
    """Create a user with a password identity."""
    session_id = _session_id(session)
    password = _password()

    async def action(application: IamApplication) -> UUID:
        user_id = await application.create_user(session_id, email, email)
        await application.create_password_identity(session_id, user_id, password)
        return user_id

    _execute(
        action,
        as_json=as_json,
        render=lambda user_id: {"user_id": str(user_id)} if as_json else str(user_id),
    )


@admin_app.command("grant")
def admin_grant(
    email: str = typer.Option(..., "--email", "-e"),
    session: str | None = _session_option(),
) -> None:
    """Grant the system administrator flag."""
    session_id = _session_id(session)
    _execute(lambda application: _grant(application, session_id, email))


async def _grant(application: IamApplication, session_id: UUID, email: str) -> None:
    """Grants the flag to the user behind ``email``."""
    users = await application.list_users(session_id)
    for user in users:
        if user.email == email:
            await application.grant_system_admin(session_id, user.user_id)
            return
    raise UnknownUserError(f"user {email!r} does not exist")


@admin_app.command("revoke")
def admin_revoke(
    email: str = typer.Option(..., "--email", "-e"),
    session: str | None = _session_option(),
) -> None:
    """Revoke the system administrator flag."""
    session_id = _session_id(session)
    _execute(lambda application: _revoke(application, session_id, email))


async def _revoke(application: IamApplication, session_id: UUID, email: str) -> None:
    """Revokes the flag from the user behind ``email``."""
    users = await application.list_users(session_id)
    for user in users:
        if user.email == email:
            await application.revoke_system_admin(session_id, user.user_id)
            return
    raise UnknownUserError(f"user {email!r} does not exist")


@admin_app.command("list")
def admin_list(
    session: str | None = _session_option(),
    as_json: bool = _json_option(),
) -> None:
    """List the system administrators."""
    session_id = _session_id(session)

    async def action(application: IamApplication) -> list[dict[str, str]]:
        await application._require_system_admin(session_id)
        return [
            {
                "user_id": str(admin.user_id),
                "username": admin.username,
                "email": admin.email,
            }
            for admin in await application.list_system_admins()
        ]

    def render(rows: list[dict[str, str]]) -> Any:
        if as_json:
            return rows
        return "\n".join(f"{row['username']} <{row['email']}>" for row in rows) or "none"

    _execute(action, as_json=as_json, render=render)


@admin_app.command("set-password")
def admin_set_password(
    email: str = typer.Option(..., "--email", "-e"),
    session: str | None = _session_option(),
) -> None:
    """Reset the password of a user without the current password."""
    session_id = _session_id(session)
    password = _password()

    async def action(application: IamApplication) -> None:
        await application.change_user_password_via_admin(session_id, email, password)

    _execute(action)


# -- tenants ----------------------------------------------------------------


@tenant_app.command("create")
def tenant_create(
    name: str = typer.Option(..., "--name", "-n"),
    description: str = typer.Option("", "--description", "-d"),
    session: str | None = _session_option(),
    as_json: bool = _json_option(),
) -> None:
    """Create a tenant."""
    session_id = _session_id(session)

    async def action(application: IamApplication) -> UUID:
        return await application.create_tenant(session_id, name, description)

    _execute(
        action,
        as_json=as_json,
        render=lambda tenant_id: {"tenant_id": str(tenant_id)} if as_json else str(tenant_id),
    )


@tenant_app.command("list")
def tenant_list(
    session: str | None = _session_option(),
    as_json: bool = _json_option(),
) -> None:
    """List the tenants."""
    session_id = _session_id(session)

    async def action(application: IamApplication) -> list[dict[str, str]]:
        await application._require_session(session_id)
        return [
            {"tenant_id": str(row.tenant_id), "name": row.name, "status": row.status}
            for row in await application.list_tenants()
        ]

    def render(rows: list[dict[str, str]]) -> Any:
        if as_json:
            return rows
        return "\n".join(f"{row['name']} ({row['status']})" for row in rows) or "none"

    _execute(action, as_json=as_json, render=render)


@tenant_app.command("add-member")
def tenant_add_member(
    tenant: str = typer.Option(..., "--tenant", "-t"),
    email: str = typer.Option(..., "--email", "-e"),
    session: str | None = _session_option(),
) -> None:
    """Add a user to a tenant."""
    session_id = _session_id(session)
    _execute(lambda application: _add_member(application, session_id, tenant, email))


async def _add_member(
    application: IamApplication,
    session_id: UUID,
    tenant: str,
    email: str,
) -> None:
    """Adds the user behind ``email`` to the named tenant."""
    tenant_id = await _tenant_id(application, tenant)
    user_id = await _user_id(application, session_id, email)
    await application.add_tenant_member(session_id, tenant_id, user_id)


@tenant_app.command("remove-member")
def tenant_remove_member(
    tenant: str = typer.Option(..., "--tenant", "-t"),
    email: str = typer.Option(..., "--email", "-e"),
    session: str | None = _session_option(),
) -> None:
    """Remove a user from a tenant."""
    session_id = _session_id(session)

    async def action(application: IamApplication) -> None:
        tenant_id = await _tenant_id(application, tenant)
        user_id = await _user_id(application, session_id, email)
        await application.remove_tenant_member(session_id, tenant_id, user_id)

    _execute(action)


async def _tenant_id(application: IamApplication, name: str) -> UUID:
    """Returns the id of the tenant with the given name."""
    for row in await application.list_tenants():
        if row.name == name:
            return row.tenant_id
    raise UnknownTenantError(f"tenant {name!r} does not exist")


async def _user_id(application: IamApplication, session_id: UUID, email: str) -> UUID:
    """Returns the id of the user with the given email."""
    for user in await application.list_users(session_id):
        if user.email == email:
            return user.user_id
    raise UnknownUserError(f"user {email!r} does not exist")


# -- auth providers ---------------------------------------------------------


@provider_app.command("create")
def provider_create(
    key: str = typer.Option(..., "--key", "-k"),
    issuer: str = typer.Option(..., "--issuer"),
    client_id: str = typer.Option(..., "--client-id"),
    secret_ref: str = typer.Option(..., "--secret-ref"),
    display_name: str = typer.Option("", "--display-name"),
    session: str | None = _session_option(),
    as_json: bool = _json_option(),
) -> None:
    """Create an OIDC auth provider."""
    session_id = _session_id(session)
    config = {
        "issuer": issuer,
        "authorization_endpoint": f"{issuer.rstrip('/')}/authorize",
        "token_endpoint": f"{issuer.rstrip('/')}/token",
        "jwks_uri": f"{issuer.rstrip('/')}/jwks",
        "client_id": client_id,
        "client_secret_ref": secret_ref,
    }

    async def action(application: IamApplication) -> UUID:
        return await application.create_auth_provider(
            session_id,
            key,
            "OIDC",
            display_name or key,
            config,
        )

    _execute(
        action,
        as_json=as_json,
        render=lambda provider_id: (
            {"provider_id": str(provider_id)} if as_json else str(provider_id)
        ),
    )


@provider_app.command("disable")
def provider_disable(
    key: str = typer.Option(..., "--key", "-k"),
    session: str | None = _session_option(),
) -> None:
    """Disable an auth provider."""
    session_id = _session_id(session)

    async def action(application: IamApplication) -> None:
        for row in await application.list_auth_providers(session_id):
            if row.provider_key == key:
                await application.change_auth_provider(
                    session_id,
                    row.provider_id,
                    status="DISABLED",
                )
                return
        raise UnknownAuthProviderError(f"auth provider {key!r} does not exist")

    _execute(action)


@provider_app.command("list")
def provider_list(
    session: str | None = _session_option(),
    as_json: bool = _json_option(),
) -> None:
    """List the auth providers."""
    session_id = _session_id(session)

    async def action(application: IamApplication) -> list[dict[str, str]]:
        return [
            {
                "provider_id": str(row.provider_id),
                "provider_key": row.provider_key,
                "status": row.status,
            }
            for row in await application.list_auth_providers(session_id)
        ]

    def render(rows: list[dict[str, str]]) -> Any:
        if as_json:
            return rows
        return "\n".join(f"{row['provider_key']} ({row['status']})" for row in rows) or "none"

    _execute(action, as_json=as_json, render=render)


# -- self service -----------------------------------------------------------


@self_app.command("change-password")
def self_change_password(session: str | None = _session_option()) -> None:
    """Change the password of the session's identity."""
    session_id = _session_id(session)
    old_password = str(typer.prompt("Current password", hide_input=True))
    new_password = _password("New password")

    async def action(application: IamApplication) -> None:
        await application.change_own_password(session_id, old_password, new_password)

    _execute(action)


__all__ = ["iam_app"]
