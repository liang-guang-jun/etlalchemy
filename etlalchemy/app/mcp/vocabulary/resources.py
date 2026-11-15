"""Vocabulary context MCP resources.

Every resource returns ``application/json`` text. Reading a resource never fails
because an object is missing: unknown or malformed references answer ``null`` or
``[]``, and a term link whose catalog target is gone carries ``dangling``.
"""

from __future__ import annotations

from fastmcp import FastMCP

from etlalchemy.app.bootstrap import Container
from etlalchemy.app.schemas.vocabulary import (
    DomainResponse,
    TermResponse,
    TermSummaryResponse,
)
from etlalchemy.shared.utils import dump, uuid_or_none
from etlalchemy.vocabulary.links import resolve_term_links


def register(mcp: FastMCP, container: Container) -> None:
    """Registers the vocabulary resources on the given server."""

    @mcp.resource(
        "vocabulary:///domains",
        name="all-domains",
        description="All live vocabulary domains, ordered by name.",
        mime_type="application/json",
    )
    async def all_domains() -> str:
        """Return every live domain."""
        rows = [
            DomainResponse.from_row(row) for row in await container.vocabulary_view().list_domains()
        ]
        return dump([row.model_dump(mode="json") for row in rows])

    @mcp.resource(
        "vocabulary:///domains/{domain_id}",
        name="domain",
        description="One live domain, or null when it does not exist.",
        mime_type="application/json",
    )
    async def domain(domain_id: str) -> str:
        """Return one domain by id."""
        key = uuid_or_none(domain_id)
        row = None if key is None else await container.vocabulary_view().get_domain(key)
        return dump(None if row is None else DomainResponse.from_row(row).model_dump(mode="json"))

    @mcp.resource(
        "vocabulary:///domains/{domain_id}/terms",
        name="domain-terms",
        description="All live terms of a domain, ordered by path.",
        mime_type="application/json",
    )
    async def domain_terms(domain_id: str) -> str:
        """Return the terms of a domain."""
        key = uuid_or_none(domain_id)
        if key is None:
            return dump([])
        rows = [
            TermSummaryResponse.from_row(row).model_dump(mode="json")
            for row in await container.vocabulary_view().list_terms(key)
        ]
        return dump(rows)

    @mcp.resource(
        "vocabulary:///terms/{term_id}",
        name="term",
        description=(
            "One term with its path, aliases and catalog links, or null when it does "
            "not exist. A link whose target is gone carries status 'dangling'."
        ),
        mime_type="application/json",
    )
    async def term(term_id: str) -> str:
        """Return one term with its aliases and resolved links."""
        key = uuid_or_none(term_id)
        if key is None:
            return dump(None)
        view = container.vocabulary_view()
        row = await view.get_term(key)
        if row is None:
            return dump(None)
        links = await resolve_term_links(
            container.catalog_view(),
            await view.list_links(key),
        )
        payload = TermResponse.from_parts(row, await view.list_aliases(key), links)
        return dump(payload.model_dump(mode="json"))

    @mcp.resource(
        "vocabulary:///terms/{term_id}/children",
        name="term-children",
        description="The direct children of a term, ordered by path.",
        mime_type="application/json",
    )
    async def term_children(term_id: str) -> str:
        """Return the direct children of a term."""
        key = uuid_or_none(term_id)
        if key is None:
            return dump([])
        view = container.vocabulary_view()
        row = await view.get_term(key)
        if row is None:
            return dump([])
        rows = [
            TermSummaryResponse.from_row(child).model_dump(mode="json")
            for child in await view.list_children(row.domain_id, key)
        ]
        return dump(rows)

    @mcp.resource(
        "vocabulary:///terms/{term_id}/descendants",
        name="term-descendants",
        description="Every live descendant of a term, ordered by path.",
        mime_type="application/json",
    )
    async def term_descendants(term_id: str) -> str:
        """Return every live descendant of a term."""
        key = uuid_or_none(term_id)
        if key is None:
            return dump([])
        view = container.vocabulary_view()
        row = await view.get_term(key)
        if row is None:
            return dump([])
        rows = [
            TermSummaryResponse.from_row(child).model_dump(mode="json")
            for child in await view.list_descendants(row.domain_id, key)
        ]
        return dump(rows)
