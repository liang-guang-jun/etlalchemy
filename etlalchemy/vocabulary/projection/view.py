"""Read model interface for the vocabulary context."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from uuid import UUID

from eventsourcing.asyncio.persistence import AsyncTrackingRecorder
from eventsourcing.persistence import Tracking

from etlalchemy.shared.utils import as_uuid as as_uuid


@dataclass(frozen=True)
class DomainRow:
    """A domain as stored in the vocabulary read model."""

    domain_id: UUID
    """ID of the domain aggregate."""
    name: str
    """Name of the domain."""
    description: str
    """Free-form description of the domain."""


@dataclass(frozen=True)
class TermRow:
    """A term as stored in the vocabulary read model."""

    term_id: UUID
    """ID of the term aggregate."""
    domain_id: UUID
    """ID of the domain that owns the term."""
    parent_id: UUID | None
    """ID of the parent term, or ``None`` for a top-level term."""
    path: str
    """Full path of the term inside its domain."""
    name: str
    """Name of the term, the last path segment."""
    definition: str
    """Definition of the term."""
    status: str
    """Lifecycle status: ``draft``, ``approved`` or ``deprecated``."""
    color: str = ""
    """Presentation colour of the term as ``#rrggbb``, or empty for none."""


@dataclass(frozen=True)
class TermLinkRow:
    """One catalog link of a term."""

    target_id: UUID
    """ID of the linked catalog, schema, table or owning table."""
    target_kind: str
    """Kind of the linked object."""
    field_name: str
    """Field name for ``field`` links, empty otherwise."""
    status: str | None = None
    """``resolved`` or ``dangling`` once the link was resolved, ``None`` before."""
    target_name: str | None = None
    """Qualified name of the target, or ``None`` when it is unknown or gone."""
    catalog_id: UUID | None = None
    """ID of the owning catalog once resolved, used by deep links."""
    schema_id: UUID | None = None
    """ID of the owning schema for schema, table and field links."""
    table_id: UUID | None = None
    """ID of the owning table for table and field links."""


@dataclass(frozen=True)
class TermSearchResult:
    """A term found by a vocabulary search."""

    domain_id: UUID
    """ID of the domain that owns the term."""
    domain_name: str
    """Name of the domain that owns the term."""
    term_id: UUID
    """ID of the matched term."""
    term_path: str
    """Path of the matched term."""
    term_name: str
    """Name of the matched term."""
    definition: str
    """Definition of the matched term."""
    status: str
    """Lifecycle status of the matched term."""
    matched_alias: str | None
    """Alias that matched, or ``None`` when the name or definition matched."""
    color: str = ""
    """Presentation colour of the matched term as ``#rrggbb``, or empty."""


class VocabularyView(AsyncTrackingRecorder, ABC):
    """Materialised view of the vocabulary aggregates.

    Every command method receives the :class:`Tracking` object of the event it
    applies and must write the view change and the tracking record in the same
    database transaction, so that replaying an already applied notification
    rolls back instead of corrupting the view.
    """

    @abstractmethod
    async def create_table(self) -> None:
        """Creates the view tables and the tracking table if they do not exist."""
        ...

    # -- domain -------------------------------------------------------------

    @abstractmethod
    async def register_domain(
        self,
        domain_id: UUID,
        name: str,
        description: str,
        tracking: Tracking,
    ) -> None:
        """Registers a domain in the view."""
        ...

    @abstractmethod
    async def change_domain(
        self,
        domain_id: UUID,
        name: str | None,
        description: str | None,
        tracking: Tracking,
    ) -> None:
        """Changes a domain, updating only the non-``None`` attributes."""
        ...

    @abstractmethod
    async def discard_domain(self, domain_id: UUID, tracking: Tracking) -> None:
        """Marks a domain, its terms and their children as discarded."""
        ...

    @abstractmethod
    async def get_domain(self, domain_id: UUID) -> DomainRow | None:
        """Returns the domain with the given ID, or ``None``."""
        ...

    @abstractmethod
    async def list_domains(self) -> list[DomainRow]:
        """Returns all live domains, ordered by name."""
        ...

    # -- term ---------------------------------------------------------------

    @abstractmethod
    async def register_term(
        self,
        term_id: UUID,
        domain_id: UUID,
        parent_id: UUID | None,
        path: str,
        name: str,
        definition: str,
        aliases: list[str],
        tracking: Tracking,
        color: str = "",
    ) -> None:
        """Registers a term and its aliases in the view."""
        ...

    @abstractmethod
    async def rename_term(
        self,
        term_id: UUID,
        new_name: str,
        new_path: str,
        tracking: Tracking,
    ) -> None:
        """Renames a term in the view."""
        ...

    @abstractmethod
    async def move_term(
        self,
        term_id: UUID,
        parent_id: UUID | None,
        new_path: str,
        tracking: Tracking,
    ) -> None:
        """Moves a term in the view."""
        ...

    @abstractmethod
    async def repath_term(self, term_id: UUID, new_path: str, tracking: Tracking) -> None:
        """Changes only the path of a term in the view."""
        ...

    @abstractmethod
    async def change_term_definition(
        self,
        term_id: UUID,
        definition: str,
        tracking: Tracking,
    ) -> None:
        """Replaces the definition of a term in the view."""
        ...

    @abstractmethod
    async def add_term_alias(self, term_id: UUID, alias: str, tracking: Tracking) -> None:
        """Adds an alias to a term in the view."""
        ...

    @abstractmethod
    async def remove_term_alias(self, term_id: UUID, alias: str, tracking: Tracking) -> None:
        """Removes an alias from a term in the view."""
        ...

    @abstractmethod
    async def set_term_status(self, term_id: UUID, status: str, tracking: Tracking) -> None:
        """Sets the lifecycle status of a term in the view."""
        ...

    @abstractmethod
    async def set_term_color(self, term_id: UUID, color: str, tracking: Tracking) -> None:
        """Sets the presentation colour of a term in the view."""
        ...

    @abstractmethod
    async def discard_term(self, term_id: UUID, tracking: Tracking) -> None:
        """Marks one term as discarded and drops its aliases and links."""
        ...

    @abstractmethod
    async def get_term(self, term_id: UUID) -> TermRow | None:
        """Returns the term with the given ID, or ``None``."""
        ...

    @abstractmethod
    async def list_terms(
        self,
        domain_id: UUID,
        status: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[TermRow]:
        """Returns the live terms of a domain, ordered by path."""
        ...

    @abstractmethod
    async def list_children(self, domain_id: UUID, parent_id: UUID | None) -> list[TermRow]:
        """Returns the direct children of a term, or the top-level terms."""
        ...

    @abstractmethod
    async def list_descendants(self, domain_id: UUID, term_id: UUID) -> list[TermRow]:
        """Returns every live descendant of a term, ordered by path."""
        ...

    @abstractmethod
    async def find_term_id(self, domain_id: UUID, path: str) -> UUID | None:
        """Returns the term ID registered under a path, or ``None``."""
        ...

    @abstractmethod
    async def list_aliases(self, term_id: UUID) -> list[str]:
        """Returns the aliases of a term, ordered by name."""
        ...

    # -- links --------------------------------------------------------------

    @abstractmethod
    async def link_term(
        self,
        term_id: UUID,
        target_id: UUID,
        target_kind: str,
        field_name: str,
        tracking: Tracking,
    ) -> None:
        """Records a catalog link of a term in the view."""
        ...

    @abstractmethod
    async def unlink_term(
        self,
        term_id: UUID,
        target_id: UUID,
        target_kind: str,
        field_name: str,
        tracking: Tracking,
    ) -> None:
        """Removes a catalog link of a term in the view."""
        ...

    @abstractmethod
    async def list_links(self, term_id: UUID) -> list[TermLinkRow]:
        """Returns the catalog links of a term."""
        ...

    # -- reverse lookups and search ----------------------------------------

    @abstractmethod
    async def terms_for_target(
        self,
        target_id: UUID,
        target_kind: str,
        field_name: str = "",
    ) -> list[TermRow]:
        """Returns the live terms linked to exactly the given target."""
        ...

    @abstractmethod
    async def terms_for_table(self, table_id: UUID) -> list[TermRow]:
        """Returns the terms linked to a table or to any of its fields."""
        ...

    @abstractmethod
    async def search_terms(
        self,
        query: str,
        domain_id: UUID | None = None,
        status: str | None = None,
        limit: int | None = None,
    ) -> list[TermSearchResult]:
        """Finds terms whose name, definition or alias contains ``query``."""
        ...
