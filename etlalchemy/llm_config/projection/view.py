"""Read model interface of the LLM provider context."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

from eventsourcing.asyncio.persistence import AsyncTrackingRecorder
from eventsourcing.persistence import Tracking

from etlalchemy.shared.utils import as_uuid as as_uuid


@dataclass(frozen=True)
class ProviderRow:
    """One LLM provider as stored in the read model."""

    provider_id: UUID
    """ID of the provider aggregate."""
    name: str
    """User-chosen name, unique among live providers."""
    kind: str
    """Provider kind, for example ``openai``."""
    endpoint: str | None
    """Base URL, or ``None`` to use the vendor default."""
    credential_ref: str | None
    """External secret reference, or ``None`` when the provider holds a token."""
    has_inline_credential: bool
    """Whether the provider holds an inline token instead of a reference."""
    default_model: str
    """Model used when a request does not name one."""
    options: dict[str, str]
    """Kind-specific model options."""
    owner_user_id: UUID
    """User that owns the provider."""
    tenant_id: UUID | None
    """Tenant the provider is scoped to, or ``None``."""
    is_public: bool
    """Whether every user may read and use the provider."""
    is_system_default: bool
    """Whether the provider is the system-wide default."""
    created_at: datetime
    """Moment the provider was created."""
    discarded_at: datetime | None = None
    """Moment of the soft delete, or ``None`` while the provider is live."""


@dataclass(frozen=True)
class ProviderShareRow:
    """One user or group a provider is shared with."""

    provider_id: UUID
    """ID of the shared provider."""
    scope: str
    """Either ``user`` or ``group``."""
    target_id: UUID
    """ID of the user or group."""


@dataclass(frozen=True)
class ProviderDefaultRow:
    """One tenant or user a provider is the default for."""

    provider_id: UUID
    """ID of the provider."""
    scope: str
    """Either ``tenant`` or ``user``."""
    target_id: UUID
    """ID of the tenant or user."""


@dataclass(frozen=True)
class ProviderDetail:
    """A provider together with its sharing and default pointers."""

    provider: ProviderRow
    """The provider itself."""
    shared_with_user_ids: list[UUID] = field(default_factory=list)
    """Users the provider is shared with."""
    shared_with_group_ids: list[UUID] = field(default_factory=list)
    """Groups the provider is shared with."""
    default_for_tenant_ids: list[UUID] = field(default_factory=list)
    """Tenants the provider is the default of."""
    default_for_user_ids: list[UUID] = field(default_factory=list)
    """Users the provider is the default of."""


class LlmProviderView(AsyncTrackingRecorder, ABC):
    """Read model of the LLM provider context."""

    @abstractmethod
    async def create_table(self) -> None:
        """Creates the tracking table and the view tables if they do not exist."""

    # -- writes -------------------------------------------------------------

    @abstractmethod
    async def register_provider(
        self,
        provider_id: UUID,
        name: str,
        kind: str,
        endpoint: str | None,
        credential_ref: str | None,
        has_inline_credential: bool,
        default_model: str,
        options: dict[str, str],
        owner_user_id: UUID,
        tenant_id: UUID | None,
        is_public: bool,
        created_at: datetime,
        tracking: Tracking,
    ) -> None:
        """Registers a provider, clearing a previous discarded marker."""

    @abstractmethod
    async def rename_provider(self, provider_id: UUID, name: str, tracking: Tracking) -> None:
        """Changes the name of a provider."""

    @abstractmethod
    async def change_endpoint(
        self,
        provider_id: UUID,
        endpoint: str | None,
        tracking: Tracking,
    ) -> None:
        """Changes the endpoint of a provider."""

    @abstractmethod
    async def change_default_model(
        self,
        provider_id: UUID,
        default_model: str,
        tracking: Tracking,
    ) -> None:
        """Changes the default model of a provider."""

    @abstractmethod
    async def change_options(
        self,
        provider_id: UUID,
        options: dict[str, str],
        tracking: Tracking,
    ) -> None:
        """Replaces the model options of a provider."""

    @abstractmethod
    async def rotate_credential(
        self,
        provider_id: UUID,
        credential_ref: str | None,
        has_inline_credential: bool,
        tracking: Tracking,
    ) -> None:
        """Updates the credential pointer of a provider."""

    @abstractmethod
    async def set_sharing(
        self,
        provider_id: UUID,
        user_ids: list[UUID],
        group_ids: list[UUID],
        tracking: Tracking,
    ) -> None:
        """Replaces every share of a provider."""

    @abstractmethod
    async def set_default(
        self,
        provider_id: UUID,
        scope: str,
        target_id: UUID | None,
        enabled: bool,
        tracking: Tracking,
    ) -> None:
        """Marks or unmarks a provider as the default of the given scope."""

    @abstractmethod
    async def discard_provider(self, provider_id: UUID, tracking: Tracking) -> None:
        """Soft-deletes a provider and drops its shares and default pointers."""

    # -- reads --------------------------------------------------------------

    @abstractmethod
    async def get_provider(self, provider_id: UUID) -> ProviderRow | None:
        """Returns a live provider, or ``None``."""

    @abstractmethod
    async def find_provider_by_name(self, name: str) -> ProviderRow | None:
        """Returns the live provider with the given name, or ``None``."""

    @abstractmethod
    async def list_providers(
        self,
        owner_user_id: UUID | None = None,
        is_public: bool | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[ProviderRow]:
        """Returns live providers, optionally filtered and paged."""

    @abstractmethod
    async def list_shares(self, provider_id: UUID) -> list[ProviderShareRow]:
        """Returns the users and groups a provider is shared with."""

    @abstractmethod
    async def list_defaults(self, provider_id: UUID) -> list[ProviderDefaultRow]:
        """Returns the tenants and users a provider is the default of."""

    @abstractmethod
    async def find_default_provider(
        self,
        scope: str,
        target_id: UUID | None = None,
    ) -> ProviderRow | None:
        """Returns the live provider that currently holds the given default."""

    @abstractmethod
    async def list_providers_shared_with(
        self,
        user_id: UUID | None = None,
        group_ids: list[UUID] | None = None,
    ) -> list[ProviderRow]:
        """Returns live providers shared with the user or any of the groups."""
