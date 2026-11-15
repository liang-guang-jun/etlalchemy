"""Target lookup port of the comment context.

Targets are weak references: the comment context stores only
``(target_type, target_id)`` and asks another read model whether the element
exists, which tenant owns it and what it is called.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True)
class TargetDescription:
    """What a target is called and which ids lead to it.

    The delivery layer turns the ids into links; the read models only know their
    own identifiers, so the routes stay the one place that owns URLs.
    """

    target_type: str
    """Type of the described target."""
    target_id: UUID
    """ID of the described target."""
    name: str
    """Name of the target itself, without its parents."""
    path: str
    """Readable path, for example ``Customer 360 / crm / contacts``."""
    catalog_id: UUID | None = None
    """Catalog the target belongs to, when it is a catalog object."""
    schema_name: str | None = None
    """Schema the target belongs to, when it is a schema, table or field."""
    table_name: str | None = None
    """Table the target belongs to, when it is a table or field."""
    field_name: str | None = None
    """Field name, for a field target."""
    model_id: UUID | None = None
    """Model the target belongs to, when it is a semantic object."""
    entity_name: str | None = None
    """Entity name, for an entity target."""
    domain_id: UUID | None = None
    """Domain the target belongs to, when it is a vocabulary object."""


class TargetLookupPort(Protocol):
    """Existence, tenancy and naming lookups for the declared target types."""

    async def exists(self, target_type: str, target_id: UUID) -> bool:
        """Returns whether the target exists."""
        ...

    async def tenant_of(self, target_type: str, target_id: UUID) -> UUID | None:
        """Returns the tenant that owns the target, or ``None``."""
        ...

    async def describe(self, target_type: str, target_id: UUID) -> TargetDescription | None:
        """Returns what the target is called, or ``None`` when it does not exist."""
        ...
