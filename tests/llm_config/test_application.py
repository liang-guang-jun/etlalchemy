"""Tests of the LLM provider application service."""

from __future__ import annotations

from uuid import uuid4

import pytest

from etlalchemy.iam.aggregates.errors import PermissionDeniedError
from etlalchemy.llm_config.aggregates.errors import (
    DuplicateProviderNameError,
    ProviderCredentialError,
    UnknownProviderError,
)
from tests.llm_config.support import FakeAuthorization, FakeSecrets, running_llm_config

TENANT = uuid4()


async def test_create_and_read_back(
    app_env: dict[str, str],
    authorization: FakeAuthorization,
    secrets: FakeSecrets,
) -> None:
    """A created provider is visible to its owner with its metadata."""
    async with running_llm_config(app_env, authorization, secrets) as (app, _, sync):
        session = authorization.add_session(tenant_id=TENANT)
        provider_id = await app.create_llm_provider(
            session.session_id,
            "my-openai",
            "openai",
            credential_ref="env:OPENAI_API_KEY",
            default_model="gpt-4o-mini",
            options={"temperature": "0.0"},
        )
        await sync()

        rows = await app.list_llm_providers(session.session_id)
        assert [row.provider_id for row in rows] == [provider_id]
        row = rows[0]
        assert row.name == "my-openai"
        assert row.kind == "openai"
        assert row.credential_ref == "env:OPENAI_API_KEY"
        assert row.has_inline_credential is False
        assert row.default_model == "gpt-4o-mini"
        assert row.options == {"temperature": "0.0"}
        assert row.tenant_id == TENANT
        assert row.is_public is False

        detail = await app.get_llm_provider(session.session_id, provider_id)
        assert detail.shared_with_user_ids == []
        assert detail.default_for_user_ids == []


async def test_duplicate_name_is_rejected(
    app_env: dict[str, str],
    authorization: FakeAuthorization,
    secrets: FakeSecrets,
) -> None:
    """Two live providers cannot share a name."""
    async with running_llm_config(app_env, authorization, secrets) as (app, _, sync):
        session = authorization.add_session()
        await app.create_llm_provider(
            session.session_id,
            "my-openai",
            "openai",
            credential_ref="env:KEY",
        )
        await sync()
        with pytest.raises(DuplicateProviderNameError):
            await app.create_llm_provider(
                session.session_id,
                "my-openai",
                "openai",
                credential_ref="env:OTHER",
            )


async def test_public_provider_requires_an_administrator(
    app_env: dict[str, str],
    authorization: FakeAuthorization,
    secrets: FakeSecrets,
) -> None:
    """A plain user cannot publish a provider to everybody."""
    async with running_llm_config(app_env, authorization, secrets) as (app, _, _):
        session = authorization.add_session()
        with pytest.raises(PermissionDeniedError):
            await app.create_llm_provider(
                session.session_id,
                "shared",
                "openai",
                credential_ref="env:KEY",
                is_public=True,
            )


async def test_change_requires_a_field(
    app_env: dict[str, str],
    authorization: FakeAuthorization,
    secrets: FakeSecrets,
) -> None:
    """An all-``None`` change is a caller error."""
    async with running_llm_config(app_env, authorization, secrets) as (app, _, _):
        session = authorization.add_session()
        provider_id = await app.create_llm_provider(
            session.session_id,
            "my-openai",
            "openai",
            credential_ref="env:KEY",
        )
        with pytest.raises(ValueError, match="at least one field"):
            await app.change_llm_provider(session.session_id, provider_id)


async def test_non_owner_cannot_change_a_provider(
    app_env: dict[str, str],
    authorization: FakeAuthorization,
    secrets: FakeSecrets,
) -> None:
    """Ownership, ``llm_provider:write`` or sysadmin are the only ways in."""
    async with running_llm_config(app_env, authorization, secrets) as (app, _, sync):
        owner = authorization.add_session()
        other = authorization.add_session(tenant_id=owner.tenant_id)
        provider_id = await app.create_llm_provider(
            owner.session_id,
            "my-openai",
            "openai",
            credential_ref="env:KEY",
        )
        await sync()
        with pytest.raises(PermissionDeniedError):
            await app.change_llm_provider(other.session_id, provider_id, name="renamed")

        authorization.grant_write(other)
        await app.change_llm_provider(other.session_id, provider_id, name="renamed")
        await sync()
        detail = await app.get_llm_provider(owner.session_id, provider_id)
        assert detail.provider.name == "renamed"


async def test_credential_for_resolves_a_reference(
    app_env: dict[str, str],
    authorization: FakeAuthorization,
    secrets: FakeSecrets,
) -> None:
    """An external reference is resolved; an inline token is returned as is."""
    secrets.add("env:OPENAI_API_KEY", "sk-from-env")
    async with running_llm_config(app_env, authorization, secrets) as (app, _, _):
        session = authorization.add_session()
        referenced = await app.create_llm_provider(
            session.session_id,
            "referenced",
            "openai",
            credential_ref="env:OPENAI_API_KEY",
        )
        inline = await app.create_llm_provider(
            session.session_id,
            "inline",
            "openai",
            token="sk-inline",
        )
        assert await app.credential_for(referenced) == "sk-from-env"
        assert await app.credential_for(inline) == "sk-inline"


async def test_credential_for_rejects_a_profile_provider(
    app_env: dict[str, str],
    authorization: FakeAuthorization,
    secrets: FakeSecrets,
) -> None:
    """A profile provider has no API key to resolve."""
    async with running_llm_config(app_env, authorization, secrets) as (app, _, _):
        session = authorization.add_session()
        provider_id = await app.create_llm_provider(
            session.session_id,
            "databricks",
            "databricks_ai_gateway",
            credential_ref="profile:team",
            default_model="databricks-claude-sonnet-4-5",
        )

        with pytest.raises(ProviderCredentialError, match="profile"):
            await app.credential_for(provider_id)


async def test_resolve_walks_the_fallback_chain(
    app_env: dict[str, str],
    authorization: FakeAuthorization,
    secrets: FakeSecrets,
) -> None:
    """User default, then tenant default, then system default, then public."""
    async with running_llm_config(app_env, authorization, secrets) as (app, _, sync):
        user = authorization.add_session(tenant_id=TENANT)
        admin = authorization.add_session(tenant_id=TENANT, is_system_admin=True)
        user_provider = await app.create_llm_provider(
            user.session_id,
            "user-default",
            "openai",
            credential_ref="env:KEY",
        )
        tenant_provider = await app.create_llm_provider(
            admin.session_id,
            "tenant-default",
            "openai",
            credential_ref="env:KEY",
        )
        system_provider = await app.create_llm_provider(
            admin.session_id,
            "system-default",
            "openai",
            credential_ref="env:KEY",
        )
        public_provider = await app.create_llm_provider(
            admin.session_id,
            "public",
            "openai",
            credential_ref="env:KEY",
            is_public=True,
        )
        await sync()
        assert await app.resolve_llm_provider(user.user_id, TENANT) is not None

        await app.share_llm_provider(
            admin.session_id,
            tenant_provider,
            user_ids=[user.user_id],
        )
        await sync()
        await app.set_default_llm_provider(user.session_id, user_provider, "user")
        await sync()
        resolved = await app.resolve_llm_provider(user.user_id, TENANT)
        assert resolved is not None
        assert resolved.provider_id == user_provider

        await app.clear_default_llm_provider(user.session_id, user_provider, "user")
        await sync()
        resolved = await app.resolve_llm_provider(user.user_id, TENANT)
        assert resolved is not None
        assert resolved.provider_id == public_provider

        await app.set_default_llm_provider(user.session_id, tenant_provider, "tenant")
        await sync()
        resolved = await app.resolve_llm_provider(user.user_id, TENANT)
        assert resolved is not None
        assert resolved.provider_id == tenant_provider

        await app.set_default_llm_provider(admin.session_id, system_provider, "system")
        await sync()
        resolved = await app.resolve_llm_provider(uuid4(), None)
        assert resolved is not None
        assert resolved.provider_id == system_provider

        await app.discard_llm_provider(admin.session_id, system_provider)
        await sync()
        resolved = await app.resolve_llm_provider(uuid4(), None)
        assert resolved is not None
        assert resolved.provider_id == public_provider


async def test_setting_a_default_clears_the_previous_one(
    app_env: dict[str, str],
    authorization: FakeAuthorization,
    secrets: FakeSecrets,
) -> None:
    """One scope never holds two defaults."""
    async with running_llm_config(app_env, authorization, secrets) as (app, _, sync):
        session = authorization.add_session()
        first = await app.create_llm_provider(
            session.session_id,
            "first",
            "openai",
            credential_ref="env:KEY",
        )
        second = await app.create_llm_provider(
            session.session_id,
            "second",
            "openai",
            credential_ref="env:KEY",
        )
        await app.set_default_llm_provider(session.session_id, first, "user")
        await sync()
        await app.set_default_llm_provider(session.session_id, second, "user")
        await sync()

        first_detail = await app.get_llm_provider(session.session_id, first)
        second_detail = await app.get_llm_provider(session.session_id, second)
        assert first_detail.default_for_user_ids == []
        assert second_detail.default_for_user_ids == [session.user_id]


async def test_sharing_through_a_parent_group(
    app_env: dict[str, str],
    authorization: FakeAuthorization,
    secrets: FakeSecrets,
) -> None:
    """Sharing with a parent group reaches a member of a nested group."""
    async with running_llm_config(app_env, authorization, secrets) as (app, _, sync):
        owner = authorization.add_session(tenant_id=TENANT)
        member = authorization.add_session(tenant_id=TENANT)
        parent = authorization.add_group()
        child = authorization.add_group(parent=parent)
        authorization.add_member(member.user_id, child)

        provider_id = await app.create_llm_provider(
            owner.session_id,
            "team-openai",
            "openai",
            credential_ref="env:KEY",
        )
        await app.share_llm_provider(owner.session_id, provider_id, group_ids=[parent])
        await sync()

        visible = await app.list_llm_providers(member.session_id)
        assert [row.provider_id for row in visible] == [provider_id]


async def test_ensure_public_provider_is_idempotent(
    app_env: dict[str, str],
    authorization: FakeAuthorization,
    secrets: FakeSecrets,
) -> None:
    """The startup bootstrap creates one provider and leaves it alone after."""
    async with running_llm_config(app_env, authorization, secrets) as (app, _, sync):
        first = await app.ensure_public_provider(
            name="default",
            kind="openai",
            endpoint=None,
            credential_ref="env:OPENAI_API_KEY",
            token=None,
            default_model="gpt-4o-mini",
        )
        await sync()
        second = await app.ensure_public_provider(
            name="default",
            kind="openai",
            endpoint=None,
            credential_ref="env:OPENAI_API_KEY",
            token=None,
            default_model="gpt-4o-mini",
        )
        assert first is not None
        assert second == first
        rows = await app.resolve_llm_provider(uuid4(), None)
        assert rows is not None
        assert rows.is_public


async def test_ensure_public_provider_updates_the_configured_fields(
    app_env: dict[str, str],
    authorization: FakeAuthorization,
    secrets: FakeSecrets,
) -> None:
    """Editing ``agent.llm`` takes effect on an existing provider of that name."""
    async with running_llm_config(app_env, authorization, secrets) as (app, _, sync):
        admin = authorization.add_session(is_system_admin=True)
        provider_id = await app.create_llm_provider(
            admin.session_id,
            "config",
            "openai",
            endpoint="https://old.example",
            credential_ref="env:OLD_KEY",
            default_model="old-model",
            options={"temperature": "0.1"},
            is_public=True,
        )
        await sync()

        returned = await app.ensure_public_provider(
            name="config",
            kind="openai",
            endpoint="https://new.example",
            credential_ref="env:NEW_KEY",
            token=None,
            default_model="new-model",
            options={"temperature": "0.5"},
        )
        await sync()

        assert returned == provider_id
        detail = await app.get_llm_provider(admin.session_id, provider_id)
        row = detail.provider
        assert row.endpoint == "https://new.example"
        assert row.default_model == "new-model"
        assert row.credential_ref == "env:NEW_KEY"
        assert row.options == {"temperature": "0.5"}
        assert row.is_system_default is True


async def test_ensure_public_provider_creates_the_configured_provider_beside_another_public_one(
    app_env: dict[str, str],
    authorization: FakeAuthorization,
    secrets: FakeSecrets,
) -> None:
    """A different public provider does not stop the configured one from existing.

    This is the switch-a-profile scenario: the database still holds the provider
    of the previous configuration. The configuration file is authoritative for
    its own name, and the new provider becomes the system default because none
    was set.
    """
    async with running_llm_config(app_env, authorization, secrets) as (app, _, sync):
        admin = authorization.add_session(is_system_admin=True)
        previous = await app.create_llm_provider(
            admin.session_id,
            "deepseek",
            "openai",
            endpoint="https://api.deepseek.com",
            credential_ref="env:DEEPSEEK_API_KEY",
            default_model="deepseek-flash",
            is_public=True,
        )
        await sync()

        created = await app.ensure_public_provider(
            name="databricks-local",
            kind="databricks_ai_gateway",
            endpoint=None,
            credential_ref="profile:DEFAULT",
            token=None,
            default_model="databricks-claude-sonnet-4-5",
        )
        await sync()

        assert created is not None
        assert created != previous
        resolved = await app.resolve_llm_provider(uuid4(), None)
        assert resolved is not None
        assert resolved.provider_id == created
        assert resolved.credential_ref == "profile:DEFAULT"
        visible = await app.list_llm_providers(admin.session_id)
        assert {row.provider_id for row in visible} == {previous, created}


async def test_discard_hides_the_provider(
    app_env: dict[str, str],
    authorization: FakeAuthorization,
    secrets: FakeSecrets,
) -> None:
    """A discarded provider disappears from reads and rejects commands."""
    async with running_llm_config(app_env, authorization, secrets) as (app, _, sync):
        session = authorization.add_session()
        provider_id = await app.create_llm_provider(
            session.session_id,
            "my-openai",
            "openai",
            credential_ref="env:KEY",
        )
        await app.set_default_llm_provider(session.session_id, provider_id, "user")
        await sync()
        await app.discard_llm_provider(session.session_id, provider_id)
        await sync()

        assert await app.list_llm_providers(session.session_id) == []
        with pytest.raises(UnknownProviderError):
            await app.get_llm_provider(session.session_id, provider_id)
