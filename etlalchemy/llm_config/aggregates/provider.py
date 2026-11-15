"""LlmProvider aggregate: one configured LLM endpoint."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from uuid import UUID

from eventsourcing.domain import Aggregate, AggregateCreated, event

from etlalchemy.llm_config.aggregates.errors import DiscardedError
from etlalchemy.llm_config.aggregates.types import (
    DefaultScope,
    validate_credential,
    validate_endpoint,
    validate_kind,
    validate_name,
)

Shares = tuple[UUID, ...]
"""Ids shared with, deduplicated and in first-seen order."""


def _normalise_ids(values: Iterable[UUID]) -> Shares:
    """Returns the given ids deduplicated while preserving first-seen order."""
    return tuple(dict.fromkeys(values))


def _normalise_options(options: Mapping[str, str] | None) -> dict[str, str]:
    """Returns a plain copy of the options mapping."""
    return {} if options is None else {key: str(value) for key, value in options.items()}


class LlmProvider(Aggregate):
    """A user-created LLM endpoint that the agent can run against.

    A provider stores only metadata and either an external ``credential_ref``
    (``env:`` / ``file:`` ...) or an inline ``token``. When inline, the token
    lives inside the event state and is therefore encrypted at rest by the
    eventsourcing cipher; the read model never stores it.

    Sharing and default pointers live on the aggregate so a whole change is one
    unit of work: the application clears the previous default by loading the
    provider that currently holds it and saving both aggregates together.
    """

    def __init__(
        self,
        name: str,
        kind: str,
        owner_user_id: UUID,
        endpoint: str | None = None,
        credential_ref: str | None = None,
        token: str | None = None,
        default_model: str = "",
        options: Mapping[str, str] | None = None,
        tenant_id: UUID | None = None,
        is_public: bool = False,
    ) -> None:
        """Initialises a provider with exactly one credential source."""
        self.name = validate_name(name)
        self.kind = validate_kind(kind)
        self.owner_user_id = owner_user_id
        self.endpoint = validate_endpoint(self.kind, endpoint, credential_ref)
        validate_credential(self.kind, credential_ref, token)
        self.credential_ref = credential_ref
        self.token = token
        self.default_model = default_model.strip()
        self.options = _normalise_options(options)
        self.tenant_id = tenant_id
        self.is_public = is_public
        self.shared_with_user_ids: Shares = ()
        self.shared_with_group_ids: Shares = ()
        self.is_system_default = False
        self.default_for_tenant_ids: Shares = ()
        self.default_for_user_ids: Shares = ()
        self._is_discarded = False

    class Event(Aggregate.Event):
        """Base class for events raised by the LLM provider aggregate."""

    @dataclass(frozen=True)
    class Started(AggregateCreated):
        """Recorded when a provider is created."""

        name: str
        """User-chosen name, unique among live providers."""
        kind: str
        """Provider kind, for example ``openai``."""
        owner_user_id: UUID
        """User that owns the provider."""
        endpoint: str | None = None
        """Base URL of the provider, when it is not the vendor default."""
        credential_ref: str | None = None
        """External secret reference, for example ``env:OPENAI_API_KEY``."""
        token: str | None = field(default=None, repr=False)
        """Inline secret, encrypted at rest by the eventsourcing cipher."""
        default_model: str = ""
        """Model used when a request does not name one."""
        options: dict[str, str] = field(default_factory=dict)
        """Kind-specific model options, for example ``temperature``."""
        tenant_id: UUID | None = None
        """Tenant the provider is scoped to, or ``None`` when it is tenant-free."""
        is_public: bool = False
        """Whether every user may read and use the provider."""

        def __post_init__(self) -> None:
            """Normalises a missing option mapping into an empty one."""
            object.__setattr__(self, "options", _normalise_options(self.options))

        def __repr__(self) -> str:
            """Renders the event without leaking the inline token."""
            return (
                f"LlmProvider.Started(name={self.name!r}, kind={self.kind!r}, "
                f"owner_user_id={self.owner_user_id!r}, endpoint={self.endpoint!r}, "
                f"credential_ref={self.credential_ref!r}, token=<redacted>, "
                f"default_model={self.default_model!r}, options={self.options!r}, "
                f"tenant_id={self.tenant_id!r}, is_public={self.is_public!r})"
            )

    @dataclass(frozen=True)
    class Renamed(Event):
        """Recorded when the provider name changes."""

        name: str
        """New, validated name."""

    @dataclass(frozen=True)
    class EndpointChanged(Event):
        """Recorded when the provider endpoint changes."""

        endpoint: str | None
        """New endpoint, or ``None`` to fall back to the vendor default."""

    @dataclass(frozen=True)
    class DefaultModelChanged(Event):
        """Recorded when the default model of the provider changes."""

        default_model: str
        """New default model; an empty string means "let the caller decide"."""

    @dataclass(frozen=True)
    class OptionsChanged(Event):
        """Recorded when the model options of the provider are replaced."""

        options: dict[str, str]
        """Complete new option mapping."""

    @dataclass(frozen=True)
    class CredentialRotated(Event):
        """Recorded when the credential reference or inline token is replaced."""

        credential_ref: str | None = None
        """New external secret reference, or ``None`` when an inline token is used."""
        token: str | None = field(default=None, repr=False)
        """New inline secret, encrypted at rest by the eventsourcing cipher."""

        def __repr__(self) -> str:
            """Renders the event without leaking the inline token."""
            return (
                f"LlmProvider.CredentialRotated("
                f"credential_ref={self.credential_ref!r}, token=<redacted>)"
            )

    @dataclass(frozen=True)
    class SharingChanged(Event):
        """Recorded when the users and groups a provider is shared with change."""

        shared_with_user_ids: Shares
        """Complete new set of users the provider is shared with."""
        shared_with_group_ids: Shares
        """Complete new set of groups the provider is shared with."""

        def __post_init__(self) -> None:
            """Normalises the decoded id lists into tuples."""
            object.__setattr__(
                self,
                "shared_with_user_ids",
                _normalise_ids(self.shared_with_user_ids),
            )
            object.__setattr__(
                self,
                "shared_with_group_ids",
                _normalise_ids(self.shared_with_group_ids),
            )

    @dataclass(frozen=True)
    class SystemDefaultChanged(Event):
        """Recorded when the provider becomes or stops being the system default."""

        enabled: bool
        """Whether the provider is the system-wide default."""

    @dataclass(frozen=True)
    class TenantDefaultChanged(Event):
        """Recorded when the provider becomes or stops being a tenant default."""

        tenant_id: UUID
        """Tenant the pointer belongs to."""
        enabled: bool
        """Whether the provider is the default of that tenant."""

    @dataclass(frozen=True)
    class UserDefaultChanged(Event):
        """Recorded when the provider becomes or stops being a user default."""

        user_id: UUID
        """User the pointer belongs to."""
        enabled: bool
        """Whether the provider is the default of that user."""

    @dataclass(frozen=True)
    class Discarded(Event):
        """Recorded when the provider is discarded."""

        by_user_id: UUID
        """User that discarded the provider."""

    # -- commands -----------------------------------------------------------

    @event(Renamed)
    def rename(self, name: str) -> None:
        """Changes the provider name."""
        self._ensure_not_discarded()
        self.name = validate_name(name)

    @event(EndpointChanged)
    def change_endpoint(self, endpoint: str | None) -> None:
        """Changes the endpoint, rejecting a kind that needs one without it."""
        self._ensure_not_discarded()
        self.endpoint = validate_endpoint(self.kind, endpoint, self.credential_ref)

    @event(DefaultModelChanged)
    def change_default_model(self, default_model: str) -> None:
        """Changes the model used when a request does not name one."""
        self._ensure_not_discarded()
        self.default_model = default_model.strip()

    @event(OptionsChanged)
    def change_options(self, options: Mapping[str, str]) -> None:
        """Replaces the model options of the provider."""
        self._ensure_not_discarded()
        self.options = _normalise_options(options)

    @event(CredentialRotated)
    def rotate_credential(
        self,
        credential_ref: str | None = None,
        token: str | None = None,
    ) -> None:
        """Replaces the credential with exactly one new source."""
        self._ensure_not_discarded()
        validate_credential(self.kind, credential_ref, token)
        validate_endpoint(self.kind, self.endpoint, credential_ref)
        self.credential_ref = credential_ref
        self.token = token

    @event(SharingChanged)
    def set_sharing(
        self,
        shared_with_user_ids: Iterable[UUID],
        shared_with_group_ids: Iterable[UUID],
    ) -> None:
        """Replaces the users and groups the provider is shared with."""
        self._ensure_not_discarded()
        self.shared_with_user_ids = _normalise_ids(shared_with_user_ids)
        self.shared_with_group_ids = _normalise_ids(shared_with_group_ids)

    @event(SystemDefaultChanged)
    def mark_system_default(self, enabled: bool) -> None:
        """Marks or unmarks the provider as the system default."""
        self._ensure_not_discarded()
        self.is_system_default = enabled

    @event(TenantDefaultChanged)
    def mark_tenant_default(self, tenant_id: UUID, enabled: bool) -> None:
        """Marks or unmarks the provider as the default of one tenant."""
        self._ensure_not_discarded()
        current = list(self.default_for_tenant_ids)
        if enabled and tenant_id not in current:
            current.append(tenant_id)
        elif not enabled and tenant_id in current:
            current.remove(tenant_id)
        self.default_for_tenant_ids = tuple(current)

    @event(UserDefaultChanged)
    def mark_user_default(self, user_id: UUID, enabled: bool) -> None:
        """Marks or unmarks the provider as the default of one user."""
        self._ensure_not_discarded()
        current = list(self.default_for_user_ids)
        if enabled and user_id not in current:
            current.append(user_id)
        elif not enabled and user_id in current:
            current.remove(user_id)
        self.default_for_user_ids = tuple(current)

    @event(Discarded)
    def discard(self, by_user_id: UUID) -> None:
        """Marks the provider as discarded and drops every pointer to it."""
        self._ensure_not_discarded()
        self._is_discarded = True
        self.is_system_default = False
        self.default_for_tenant_ids = ()
        self.default_for_user_ids = ()

    # -- queries ------------------------------------------------------------

    @property
    def is_discarded(self) -> bool:
        """Returns whether the provider has been discarded."""
        return self._is_discarded

    def is_shared_with_user(self, user_id: UUID) -> bool:
        """Returns whether the provider is shared with the given user."""
        return user_id in self.shared_with_user_ids

    def is_shared_with_any_group(self, group_ids: Iterable[UUID]) -> bool:
        """Returns whether the provider is shared with any of the given groups."""
        return any(group_id in self.shared_with_group_ids for group_id in group_ids)

    def is_default_for(self, scope: DefaultScope, target_id: UUID | None) -> bool:
        """Returns whether the provider is the default of the given scope."""
        if scope == "system":
            return self.is_system_default
        if scope == "tenant":
            return target_id is not None and target_id in self.default_for_tenant_ids
        return target_id is not None and target_id in self.default_for_user_ids

    def _ensure_not_discarded(self) -> None:
        """Raises DiscardedError when the provider has been discarded."""
        if self._is_discarded:
            msg = "provider is discarded"
            raise DiscardedError(msg)

    def __repr__(self) -> str:
        """Renders the aggregate without leaking the inline token."""
        return (
            f"LlmProvider(id={self.id}, name={self.name!r}, kind={self.kind!r}, "
            f"owner_user_id={self.owner_user_id!r}, endpoint={self.endpoint!r}, "
            f"credential_ref={self.credential_ref!r}, token=<redacted>, "
            f"default_model={self.default_model!r}, is_public={self.is_public!r})"
        )
