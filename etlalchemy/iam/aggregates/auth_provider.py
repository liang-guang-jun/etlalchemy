"""AuthProvider aggregate: system-level configuration of an identity source."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from eventsourcing.domain import Aggregate, AggregateCreated, event

from etlalchemy.iam.aggregates.errors import (
    DiscardedError,
    IamValidationError,
    InvalidProviderConfigError,
)
from etlalchemy.iam.aggregates.types import (
    OidcConfig,
    ProviderStatus,
    ensure_provider_status,
    validate_provider_key,
)


class AuthProvider(Aggregate):
    """Aggregate root for one external identity source.

    The aggregate stores the configuration as a JSON-safe mapping of strings so
    the default transcoder can persist it. ``client_secret_ref`` points at the
    secret store; the ``client_secret`` itself never enters the event stream.
    """

    def __init__(
        self,
        provider_key: str,
        kind: str,
        display_name: str,
        config: dict[str, str],
        tenant_id: UUID | None = None,
    ) -> None:
        """Initialises an enabled provider after validating its configuration."""
        validate_provider_key(provider_key)
        if kind != "OIDC":
            msg = f"unsupported auth provider kind: {kind!r}"
            raise IamValidationError(msg)
        self.provider_key = provider_key
        self.kind = kind
        self.display_name = display_name
        self.tenant_id = tenant_id
        self.config = _normalise_config(dict(config))
        self.status: ProviderStatus = "ENABLED"
        self._is_discarded = False

    class Event(Aggregate.Event):
        """Base class for events raised by the auth provider aggregate."""

    @dataclass(frozen=True)
    class Started(AggregateCreated):
        """Recorded when an auth provider is created."""

        provider_key: str
        """Unique key of the provider."""
        kind: str
        """Kind of the provider; only ``OIDC`` exists in v1."""
        display_name: str
        """Human readable name."""
        config: dict[str, str]
        """JSON-safe configuration mapping."""
        tenant_id: UUID | None = None
        """Tenant the provider belongs to, or ``None`` when global."""

    @dataclass(frozen=True)
    class Changed(Event):
        """Recorded when the display name or status changes."""

        display_name: str | None = None
        """New display name, or ``None`` when unchanged."""
        status: str | None = None
        """New status, or ``None`` when unchanged."""

    @dataclass(frozen=True)
    class ConfigUpdated(Event):
        """Recorded when the provider configuration is replaced."""

        config: dict[str, str]
        """New JSON-safe configuration mapping."""

    @dataclass(frozen=True)
    class Discarded(Event):
        """Recorded when the provider is discarded."""

    @event(Changed)
    def change(self, display_name: str | None = None, status: str | None = None) -> None:
        """Changes the display name and/or status of the provider."""
        self._ensure_not_discarded()
        if display_name is None and status is None:
            msg = "change() requires at least one field"
            raise ValueError(msg)
        checked = None if status is None else ensure_provider_status(status)
        if display_name is not None:
            self.display_name = display_name
        if checked is not None:
            self.status = checked

    @event(ConfigUpdated)
    def update_config(self, config: dict[str, str]) -> None:
        """Replaces the provider configuration; the kind cannot change."""
        self._ensure_not_discarded()
        self.config = _normalise_config(dict(config))

    @event(Discarded)
    def discard(self) -> None:
        """Marks the provider as discarded."""
        self._ensure_not_discarded()
        self._is_discarded = True

    def oidc(self) -> OidcConfig:
        """Returns the configuration as a validated OIDC value object."""
        return OidcConfig.from_mapping(self.config)

    @property
    def is_discarded(self) -> bool:
        """Returns whether the provider has been discarded.

        ``status`` keeps its last value after a discard, so callers that need to
        reject a discarded provider must check this flag as well.
        """
        return self._is_discarded

    def _ensure_not_discarded(self) -> None:
        """Raises DiscardedError when the provider has been discarded."""
        if self._is_discarded:
            msg = "auth provider is discarded"
            raise DiscardedError(msg)


def _normalise_config(config: dict[str, str]) -> dict[str, str]:
    """Validates an OIDC configuration and returns its canonical mapping."""
    if not config:
        msg = "auth provider config must not be empty"
        raise InvalidProviderConfigError(msg)
    return OidcConfig.from_mapping(config).to_mapping()
