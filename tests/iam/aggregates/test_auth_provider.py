"""Tests for the auth provider aggregate and its OIDC configuration."""

from typing import Any
from uuid import uuid4

import pytest

from etlalchemy.iam.aggregates.auth_provider import AuthProvider
from etlalchemy.iam.aggregates.errors import (
    DiscardedError,
    IamValidationError,
    InvalidProviderConfigError,
)
from etlalchemy.iam.aggregates.types import OidcConfig, Permission


def oidc_mapping(**overrides: str) -> dict[str, str]:
    """Returns a valid OIDC configuration mapping, with optional overrides."""
    mapping = {
        "issuer": "https://idp.example",
        "authorization_endpoint": "https://idp.example/authorize",
        "token_endpoint": "https://idp.example/token",
        "jwks_uri": "https://idp.example/jwks",
        "client_id": "etlalchemy",
        "client_secret_ref": "env:OIDC_SECRET",
        "userinfo_endpoint": "",
        "scopes": "openid email",
        "redirect_uris": "",
    }
    mapping.update(overrides)
    return mapping


def replay(events: list[Any]) -> AuthProvider:
    """Rebuilds a provider by applying the given events in order."""
    aggregate: Any = None
    for event in events:
        aggregate = event.mutate(aggregate)
    assert isinstance(aggregate, AuthProvider)
    return aggregate


def test_started_event_carries_the_normalised_config() -> None:
    """A provider stores its config as a JSON-safe mapping of strings."""
    tenant_id = uuid4()
    provider = AuthProvider("corp", "OIDC", "Corporate", oidc_mapping(), tenant_id)

    assert provider.status == "ENABLED"
    assert provider.config["scopes"] == "openid email"
    events = provider.pending_events
    event = events[0]
    assert isinstance(event, AuthProvider.Started)
    assert event.config == provider.config
    assert replay(events).config == provider.config


def test_only_oidc_and_valid_keys_are_accepted() -> None:
    """The kind is fixed to OIDC and provider keys are restricted."""
    with pytest.raises(IamValidationError):
        AuthProvider("corp", "SAML", "Corporate", oidc_mapping())
    with pytest.raises(IamValidationError):
        AuthProvider("Corporate IdP", "OIDC", "Corporate", oidc_mapping())


def test_config_requires_the_oidc_endpoints() -> None:
    """A missing endpoint or an insecure URL is rejected."""
    with pytest.raises(InvalidProviderConfigError):
        AuthProvider("corp", "OIDC", "Corporate", oidc_mapping(jwks_uri=""))
    with pytest.raises(InvalidProviderConfigError):
        AuthProvider("corp", "OIDC", "Corporate", oidc_mapping(issuer="http://idp.example"))


def test_localhost_http_endpoints_are_allowed() -> None:
    """Development providers may use plain http on localhost."""
    provider = AuthProvider(
        "local",
        "OIDC",
        "Local",
        oidc_mapping(issuer="http://localhost:9000"),
    )
    assert provider.oidc().issuer == "http://localhost:9000"


def test_changing_and_updating_a_provider_is_replayable() -> None:
    """Status, display name and configuration changes survive replay."""
    provider = AuthProvider("corp", "OIDC", "Corporate", oidc_mapping())
    provider.change(display_name="Corp IdP", status="DISABLED")
    provider.update_config(oidc_mapping(issuer="https://idp2.example"))

    restored = replay(provider.pending_events)
    assert restored.status == "DISABLED"
    assert restored.display_name == "Corp IdP"
    assert restored.config["issuer"] == "https://idp2.example"

    event = provider.pending_events[-1]
    assert isinstance(event, AuthProvider.ConfigUpdated)


def test_discarded_provider_rejects_every_command() -> None:
    """A discarded provider refuses changes and configuration updates."""
    provider = AuthProvider("corp", "OIDC", "Corporate", oidc_mapping())
    provider.discard()

    with pytest.raises(DiscardedError):
        provider.change(status="DISABLED")
    with pytest.raises(DiscardedError):
        provider.update_config(oidc_mapping())
    with pytest.raises(DiscardedError):
        provider.discard()


def test_oidc_config_round_trips_through_its_mapping() -> None:
    """The OIDC value object normalises scopes and re-reads its own mapping."""
    config = OidcConfig.from_mapping(
        oidc_mapping(scopes="openid profile", redirect_uris="https://app.example/cb")
    )

    assert config.scopes == ("openid", "profile")
    assert config.redirect_uris == ("https://app.example/cb",)
    assert OidcConfig.from_mapping(config.to_mapping()).to_mapping() == config.to_mapping()


def test_oidc_config_rejects_an_insecure_redirect_uri() -> None:
    """Redirect URIs follow the same https (or localhost) rule as the endpoints."""
    with pytest.raises(InvalidProviderConfigError):
        OidcConfig.from_mapping(oidc_mapping(redirect_uris="http://app.example/cb"))


def test_discarding_a_provider_exposes_the_flag() -> None:
    """``status`` keeps its value after a discard, so the flag is the signal."""
    provider = AuthProvider("corp", "OIDC", "Corporate", oidc_mapping())
    assert provider.is_discarded is False

    provider.discard()
    assert provider.is_discarded is True
    assert provider.status == "ENABLED"


def test_permission_parsing_is_idempotent() -> None:
    """Permissions keep a colon inside the resource and normalise to text."""
    permission = Permission.parse("project:alpha/doc:read")

    assert (permission.resource, permission.action) == ("project:alpha/doc", "read")
    assert Permission.parse(str(permission)) == permission

    for invalid in ("doc", ":read", "doc:", "doc:rea d"):
        with pytest.raises(IamValidationError):
            Permission.parse(invalid)
