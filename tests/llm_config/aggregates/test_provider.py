"""Tests of the LlmProvider aggregate."""

from __future__ import annotations

from uuid import uuid4

import pytest
from etlalchemy.llm_config.aggregates.errors import (
    DiscardedError,
    InvalidProviderKindError,
    InvalidProviderNameError,
    MissingEndpointError,
    ProviderCredentialError,
)
from etlalchemy.llm_config.aggregates.provider import LlmProvider

OWNER = uuid4()
TENANT = uuid4()


def make_provider(**overrides: object) -> LlmProvider:
    """Builds an OpenAI provider with a reference credential."""
    parameters: dict[str, object] = {
        "name": "my-openai",
        "kind": "openai",
        "owner_user_id": OWNER,
        "credential_ref": "env:OPENAI_API_KEY",
        "default_model": "gpt-4o-mini",
    }
    parameters.update(overrides)
    return LlmProvider(**parameters)  # type: ignore[arg-type]


def test_create_normalises_name_and_options() -> None:
    """The name is stripped and the options are copied into a plain mapping."""
    options = {"temperature": "0.0"}
    provider = make_provider(name="  my-openai  ", options=options)
    options["temperature"] = "1.0"
    assert provider.name == "my-openai"
    assert provider.options == {"temperature": "0.0"}
    assert provider.is_public is False
    assert provider.is_system_default is False


def test_create_requires_one_credential() -> None:
    """Both or neither credential source is rejected."""
    with pytest.raises(ProviderCredentialError):
        make_provider(credential_ref="env:KEY", token="inline")
    with pytest.raises(ProviderCredentialError):
        make_provider(credential_ref=None, token=None)
    with pytest.raises(ProviderCredentialError):
        make_provider(credential_ref=None, token="   ")


def test_create_rejects_a_blank_name() -> None:
    """A blank name is a domain error."""
    with pytest.raises(InvalidProviderNameError):
        make_provider(name="   ")


def test_create_rejects_an_unknown_kind() -> None:
    """Only the supported kinds are accepted."""
    with pytest.raises(InvalidProviderKindError):
        make_provider(kind="anthropic")


def test_databricks_requires_an_endpoint() -> None:
    """The gateway kind cannot be built without a workspace URL."""
    with pytest.raises(MissingEndpointError):
        make_provider(kind="databricks_ai_gateway", endpoint=None)
    provider = make_provider(
        kind="databricks_ai_gateway",
        endpoint=" https://example.cloud.databricks.com ",
    )
    assert provider.endpoint == "https://example.cloud.databricks.com"


def test_a_profile_provider_may_omit_the_endpoint() -> None:
    """A Databricks profile already carries the workspace host."""
    provider = make_provider(
        kind="databricks_ai_gateway",
        endpoint=None,
        credential_ref="profile:team",
    )

    assert provider.endpoint is None
    assert provider.credential_ref == "profile:team"


def test_a_profile_is_only_supported_by_the_databricks_kind() -> None:
    """An OpenAI provider cannot resolve a Databricks CLI profile."""
    with pytest.raises(ProviderCredentialError, match="profile"):
        make_provider(kind="openai", credential_ref="profile:team")


def test_rotating_a_profile_to_a_token_needs_an_endpoint() -> None:
    """The empty endpoint of a profile cannot survive a token rotation."""
    provider = make_provider(
        kind="databricks_ai_gateway",
        endpoint=None,
        credential_ref="profile:team",
    )

    with pytest.raises(MissingEndpointError):
        provider.rotate_credential(token="dapi-inline")


def test_rotate_credential_switches_the_source() -> None:
    """Rotating replaces the reference with an inline token and back."""
    provider = make_provider()
    provider.rotate_credential(token="sk-inline")
    assert provider.credential_ref is None
    assert provider.token == "sk-inline"
    provider.rotate_credential(credential_ref="env:OTHER")
    assert provider.credential_ref == "env:OTHER"
    assert provider.token is None
    with pytest.raises(ProviderCredentialError):
        provider.rotate_credential()


def test_set_sharing_deduplicates() -> None:
    """Shares are deduplicated while keeping first-seen order."""
    provider = make_provider()
    first, second = uuid4(), uuid4()
    provider.set_sharing([first, second, first], [])
    assert provider.shared_with_user_ids == (first, second)
    assert provider.is_shared_with_user(first)
    assert provider.is_shared_with_any_group([]) is False


def test_defaults_are_idempotent() -> None:
    """Marking the same default twice keeps one pointer, clearing removes it."""
    provider = make_provider()
    provider.mark_user_default(OWNER, True)
    provider.mark_user_default(OWNER, True)
    assert provider.default_for_user_ids == (OWNER,)
    assert provider.is_default_for("user", OWNER)
    provider.mark_user_default(OWNER, False)
    provider.mark_user_default(OWNER, False)
    assert provider.default_for_user_ids == ()
    assert provider.is_default_for("user", OWNER) is False

    provider.mark_tenant_default(TENANT, True)
    assert provider.is_default_for("tenant", TENANT)
    provider.mark_system_default(True)
    assert provider.is_default_for("system", None)


def test_discard_clears_pointers_and_blocks_commands() -> None:
    """A discarded provider drops its pointers and rejects every command."""
    provider = make_provider()
    provider.mark_user_default(OWNER, True)
    provider.mark_system_default(True)
    provider.discard(OWNER)
    assert provider.is_discarded
    assert provider.default_for_user_ids == ()
    assert provider.is_system_default is False
    with pytest.raises(DiscardedError):
        provider.rename("other")
    with pytest.raises(DiscardedError):
        provider.discard(OWNER)


def test_repr_hides_the_inline_token() -> None:
    """Neither the aggregate nor its events render the secret."""
    provider = make_provider(credential_ref=None, token="sk-secret")
    assert "sk-secret" not in repr(provider)
    assert "sk-secret" not in repr(provider.pending_events[0])
