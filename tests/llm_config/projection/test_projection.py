"""Tests for the LLM provider projection runner."""

from __future__ import annotations

from uuid import uuid4

from tests.llm_config.support import FakeAuthorization, FakeSecrets, running_llm_config

TENANT = uuid4()


async def test_projection_materialises_shares_and_defaults(
    app_env: dict[str, str],
    authorization: FakeAuthorization,
    secrets: FakeSecrets,
) -> None:
    """Shares, tenant pointers and the system pointer reach the read model."""
    async with running_llm_config(app_env, authorization, secrets) as (app, view, sync):
        admin = authorization.add_session(tenant_id=TENANT, is_system_admin=True)
        friend = authorization.add_user()
        group = authorization.add_group()
        provider_id = await app.create_llm_provider(
            admin.session_id,
            "my-openai",
            "openai",
            credential_ref="env:OPENAI_API_KEY",
            default_model="gpt-4o-mini",
        )
        await app.share_llm_provider(
            admin.session_id,
            provider_id,
            user_ids=[friend],
            group_ids=[group],
        )
        await app.set_default_llm_provider(admin.session_id, provider_id, "tenant", TENANT)
        await app.set_default_llm_provider(admin.session_id, provider_id, "user")
        await app.set_default_llm_provider(admin.session_id, provider_id, "system")
        await sync()

        shares = await view.list_shares(provider_id)
        assert {(row.scope, row.target_id) for row in shares} == {
            ("user", friend),
            ("group", group),
        }

        defaults = await view.list_defaults(provider_id)
        assert {(row.scope, row.target_id) for row in defaults} == {
            ("tenant", TENANT),
            ("user", admin.user_id),
        }

        row = await view.get_provider(provider_id)
        assert row is not None
        assert row.is_system_default is True
        assert await view.find_default_provider("system") == row
        assert await view.find_default_provider("tenant", TENANT) == row


async def test_projection_clears_a_previous_default(
    app_env: dict[str, str],
    authorization: FakeAuthorization,
    secrets: FakeSecrets,
) -> None:
    """The provider that loses the pointer stops being the default in the view."""
    async with running_llm_config(app_env, authorization, secrets) as (app, view, sync):
        admin = authorization.add_session(is_system_admin=True)
        first = await app.create_llm_provider(
            admin.session_id,
            "first",
            "openai",
            credential_ref="env:KEY",
        )
        second = await app.create_llm_provider(
            admin.session_id,
            "second",
            "openai",
            credential_ref="env:KEY",
        )
        await app.set_default_llm_provider(admin.session_id, first, "system")
        await sync()
        await app.set_default_llm_provider(admin.session_id, second, "system")
        await sync()

        current = await view.find_default_provider("system")
        assert current is not None
        assert current.provider_id == second


async def test_projection_cascades_the_discard(
    app_env: dict[str, str],
    authorization: FakeAuthorization,
    secrets: FakeSecrets,
) -> None:
    """Discarding a provider removes it, its shares and its pointers."""
    async with running_llm_config(app_env, authorization, secrets) as (app, view, sync):
        admin = authorization.add_session(is_system_admin=True)
        friend = authorization.add_user()
        provider_id = await app.create_llm_provider(
            admin.session_id,
            "my-openai",
            "openai",
            credential_ref="env:KEY",
        )
        await app.share_llm_provider(admin.session_id, provider_id, user_ids=[friend])
        await app.set_default_llm_provider(admin.session_id, provider_id, "system")
        await sync()
        assert await view.list_shares(provider_id) != []

        await app.discard_llm_provider(admin.session_id, provider_id)
        await sync()

        assert await view.get_provider(provider_id) is None
        assert await view.list_shares(provider_id) == []
        assert await view.list_defaults(provider_id) == []
        assert await view.find_default_provider("system") is None
