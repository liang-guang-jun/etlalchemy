"""Response models of the vocabulary context."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Self
from uuid import UUID

from pydantic import BaseModel

from etlalchemy.vocabulary.projection.view import (
    DomainRow,
    TermLinkRow,
    TermRow,
    TermSearchResult,
)


class DomainResponse(BaseModel):
    """A domain as exposed by the delivery layers."""

    domain_id: UUID
    """ID of the domain aggregate."""
    name: str
    """Name of the domain."""
    description: str
    """Free-form description of the domain."""

    @classmethod
    def from_row(cls, row: DomainRow) -> Self:
        """Builds the model from a read model row."""
        return cls(domain_id=row.domain_id, name=row.name, description=row.description)


class TermSummaryResponse(BaseModel):
    """A term without its aliases and links, as listed by a collection."""

    term_id: UUID
    """ID of the term aggregate."""
    domain_id: UUID
    """ID of the domain that owns the term."""
    parent_id: UUID | None
    """ID of the parent term, or null for a top-level term."""
    path: str
    """Full path of the term inside its domain."""
    name: str
    """Name of the term."""
    definition: str
    """Definition of the term."""
    status: str
    """Lifecycle status of the term."""
    color: str = ""
    """Presentation colour of the term as ``#rrggbb``, or empty for none."""

    @classmethod
    def from_row(cls, row: TermRow) -> Self:
        """Builds the model from a read model row."""
        return cls(
            term_id=row.term_id,
            domain_id=row.domain_id,
            parent_id=row.parent_id,
            path=row.path,
            name=row.name,
            definition=row.definition,
            status=row.status,
            color=row.color,
        )


class TermLinkResponse(BaseModel):
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
    """ID of the owning catalog once resolved."""
    schema_id: UUID | None = None
    """ID of the owning schema for schema, table and field links."""
    table_id: UUID | None = None
    """ID of the owning table for table and field links."""

    @classmethod
    def from_row(cls, row: TermLinkRow) -> Self:
        """Builds the model from a read model row."""
        return cls(
            target_id=row.target_id,
            target_kind=row.target_kind,
            field_name=row.field_name,
            status=row.status,
            target_name=row.target_name,
            catalog_id=row.catalog_id,
            schema_id=row.schema_id,
            table_id=row.table_id,
        )


class TermResponse(BaseModel):
    """A term with its aliases and catalog links."""

    term_id: UUID
    """ID of the term aggregate."""
    domain_id: UUID
    """ID of the domain that owns the term."""
    parent_id: UUID | None
    """ID of the parent term, or null for a top-level term."""
    path: str
    """Full path of the term inside its domain."""
    name: str
    """Name of the term."""
    definition: str
    """Definition of the term."""
    status: str
    """Lifecycle status of the term."""
    aliases: list[str]
    """Aliases of the term, ordered by name."""
    links: list[TermLinkResponse]
    """Catalog links of the term."""
    color: str = ""
    """Presentation colour of the term as ``#rrggbb``, or empty for none."""

    @classmethod
    def from_parts(
        cls,
        row: TermRow,
        aliases: list[str],
        links: Sequence[TermLinkRow],
    ) -> Self:
        """Builds the model from a term row and its resolved links."""
        return cls(
            term_id=row.term_id,
            domain_id=row.domain_id,
            parent_id=row.parent_id,
            path=row.path,
            name=row.name,
            definition=row.definition,
            status=row.status,
            color=row.color,
            aliases=aliases,
            links=[TermLinkResponse.from_row(link) for link in links],
        )


class TermSearchResultResponse(BaseModel):
    """One term found by a vocabulary search."""

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

    @classmethod
    def from_row(cls, row: TermSearchResult) -> Self:
        """Builds the model from a read model search result."""
        return cls(
            domain_id=row.domain_id,
            domain_name=row.domain_name,
            term_id=row.term_id,
            term_path=row.term_path,
            term_name=row.term_name,
            definition=row.definition,
            status=row.status,
            matched_alias=row.matched_alias,
            color=row.color,
        )


class DomainCreatedResponse(BaseModel):
    """Result of ``create_domain``."""

    domain_id: UUID
    """ID of the new domain."""


class TermCreatedResponse(BaseModel):
    """Result of ``create_term``."""

    term_id: UUID
    """ID of the new term."""
