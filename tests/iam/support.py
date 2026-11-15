"""Helpers for the IAM application tests."""

from __future__ import annotations

from typing import Any

from etlalchemy._vendor.eventsourcing.asyncio.projection import AsyncProjectionRunner
from etlalchemy.iam.adapters.passwords import PasswordHasher
from etlalchemy.iam.adapters.secrets import EnvSecretsResolver
from etlalchemy.iam.application import IamApplication, IamOptions, SessionRef
from etlalchemy.iam.authorization import CasbinAuthorizer


def build_application(
    env: dict[str, str],
    view: Any,
    options: IamOptions | None = None,
) -> IamApplication:
    """Builds an IAM application bound to the given read model."""
    return IamApplication(
        view=view,
        hasher=PasswordHasher(),
        secrets_resolver=EnvSecretsResolver(),
        authorizer=CasbinAuthorizer(reload_interval_seconds=0.0),
        options=options or IamOptions(password_min_length=8, api_key_pepper="test-pepper"),
        env=env,
    )


async def sync(
    runner: AsyncProjectionRunner[Any, Any],
    application: IamApplication,
) -> None:
    """Waits until the view consumed every notification it subscribes to.

    Some aggregate events (attaching or detaching an identity on the user) are not
    projected, so the follower never tracks them; waiting for the highest
    *projected* notification keeps the check deterministic.
    """
    last = await application.recorder.max_notification_id()
    if last is None:
        return
    notifications = await application.recorder.select_notifications(1, last)
    projected = [
        notification.id
        for notification in notifications
        if notification.topic in runner.projection.topics
    ]
    if projected:
        await runner.wait(max(projected), timeout=5.0)


async def login(
    application: IamApplication,
    runner: AsyncProjectionRunner[Any, Any],
    login_name: str,
    password: str,
    tenant_id: Any = None,
) -> SessionRef:
    """Authenticates with a password and waits for the session row."""
    session = await application.authenticate_password(login_name, password, tenant_id)
    await sync(runner, application)
    return session


async def login_api_key(
    application: IamApplication,
    runner: AsyncProjectionRunner[Any, Any],
    secret: str,
) -> SessionRef:
    """Authenticates with an API key and waits for the session row."""
    session = await application.authenticate_api_key(secret)
    await sync(runner, application)
    return session
