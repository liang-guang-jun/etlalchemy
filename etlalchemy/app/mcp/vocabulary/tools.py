"""Vocabulary context MCP tools."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastmcp import FastMCP
from pydantic import Field

from etlalchemy.app.bootstrap import Container
from etlalchemy.app.mcp.errors import mcp_error_guard
from etlalchemy.app.schemas.common import OkResponse
from etlalchemy.app.schemas.vocabulary import (
    DomainCreatedResponse,
    DomainResponse,
    TermCreatedResponse,
    TermResponse,
    TermSearchResultResponse,
    TermSummaryResponse,
)
from etlalchemy.shared.utils import uuid_or_none
from etlalchemy.vocabulary.aggregates.types import TARGET_KINDS
from etlalchemy.vocabulary.links import resolve_term_links

TERM_REFERENCE = (
    "Term id (UUID) or full path such as 'Revenue/ARR'. A bare name only matches a top-level term."
)
"""Description shared by every tool that accepts a term reference."""


def register(mcp: FastMCP, container: Container) -> None:
    """Registers the vocabulary tools on the given server."""
    # ---- domain ----------------------------------------------------------

    @mcp.tool(
        name="create_domain",
        description="Create a vocabulary domain and return the id of the new aggregate.",
    )
    async def create_domain(
        name: Annotated[str, Field(description="Name of the new domain.")],
        description: Annotated[
            str,
            Field(description="Free-form description of the domain."),
        ] = "",
    ) -> DomainCreatedResponse:
        """Create a domain."""
        with mcp_error_guard():
            domain_id = await container.vocabulary_application().create_domain(
                name,
                description,
            )
        return DomainCreatedResponse(domain_id=domain_id)

    @mcp.tool(
        name="change_domain",
        description="Change the name and/or description of a domain.",
    )
    async def change_domain(
        domain_id: Annotated[UUID, Field(description="ID of the domain.")],
        name: Annotated[
            str | None,
            Field(description="New name, or null to keep the current one."),
        ] = None,
        description: Annotated[
            str | None,
            Field(description="New description, or null to keep the current one."),
        ] = None,
    ) -> OkResponse:
        """Change a domain."""
        with mcp_error_guard():
            await container.vocabulary_application().change_domain(
                domain_id,
                name,
                description,
            )
        return OkResponse()

    @mcp.tool(
        name="discard_domain",
        description="Discard a domain together with every term it owns.",
        annotations={"destructiveHint": True},
    )
    async def discard_domain(
        domain_id: Annotated[UUID, Field(description="ID of the domain to discard.")],
    ) -> OkResponse:
        """Discard a domain."""
        with mcp_error_guard():
            await container.vocabulary_application().discard_domain(domain_id)
        return OkResponse()

    # ---- term commands ---------------------------------------------------

    @mcp.tool(
        name="create_term",
        description=(
            "Create a draft term and return the id of the new aggregate. Pass "
            "parent to place the term under another term; omit it for a top-level term."
        ),
    )
    async def create_term(
        domain_id: Annotated[UUID, Field(description="ID of the owning domain.")],
        term_name: Annotated[str, Field(description="Name of the new term.")],
        definition: Annotated[str, Field(description="Initial definition of the term.")],
        aliases: Annotated[
            list[str] | None,
            Field(description="Initial aliases of the term, or null for none."),
        ] = None,
        parent: Annotated[
            str | None,
            Field(description=f"Parent term reference. {TERM_REFERENCE}"),
        ] = None,
        color: Annotated[
            str,
            Field(description="Colour as #rrggbb, or an empty string for none."),
        ] = "",
    ) -> TermCreatedResponse:
        """Create a term."""
        with mcp_error_guard():
            term_id = await container.vocabulary_application().create_term(
                domain_id,
                term_name,
                definition,
                aliases,
                parent,
                color,
            )
        return TermCreatedResponse(term_id=term_id)

    @mcp.tool(
        name="change_term_color",
        description=(
            "Set the presentation colour of a term as #rrggbb. Pass an empty "
            "string to clear it. Allowed in every live status."
        ),
    )
    async def change_term_color(
        domain_id: Annotated[UUID, Field(description="ID of the owning domain.")],
        term: Annotated[str, Field(description=TERM_REFERENCE)],
        color: Annotated[str, Field(description="Colour as #rrggbb, empty to clear.")],
    ) -> OkResponse:
        """Change a term colour."""
        with mcp_error_guard():
            await container.vocabulary_application().change_term_color(
                domain_id,
                term,
                color,
            )
        return OkResponse()

    @mcp.tool(
        name="change_term_definition",
        description="Replace the definition of a draft term.",
    )
    async def change_term_definition(
        domain_id: Annotated[UUID, Field(description="ID of the owning domain.")],
        term: Annotated[str, Field(description=TERM_REFERENCE)],
        definition: Annotated[str, Field(description="New definition of the term.")],
    ) -> OkResponse:
        """Change a term definition."""
        with mcp_error_guard():
            await container.vocabulary_application().change_term_definition(
                domain_id,
                term,
                definition,
            )
        return OkResponse()

    @mcp.tool(
        name="add_term_alias",
        description="Add an alias to a draft term.",
    )
    async def add_term_alias(
        domain_id: Annotated[UUID, Field(description="ID of the owning domain.")],
        term: Annotated[str, Field(description=TERM_REFERENCE)],
        alias: Annotated[str, Field(description="Alias to add.")],
    ) -> OkResponse:
        """Add a term alias."""
        with mcp_error_guard():
            await container.vocabulary_application().add_term_alias(
                domain_id,
                term,
                alias,
            )
        return OkResponse()

    @mcp.tool(
        name="remove_term_alias",
        description="Remove an alias from a draft term.",
        annotations={"destructiveHint": True},
    )
    async def remove_term_alias(
        domain_id: Annotated[UUID, Field(description="ID of the owning domain.")],
        term: Annotated[str, Field(description=TERM_REFERENCE)],
        alias: Annotated[str, Field(description="Alias to remove.")],
    ) -> OkResponse:
        """Remove a term alias."""
        with mcp_error_guard():
            await container.vocabulary_application().remove_term_alias(
                domain_id,
                term,
                alias,
            )
        return OkResponse()

    @mcp.tool(
        name="rename_term",
        description=(
            "Rename a draft or approved term. Every descendant moves to the new path; "
            "the whole command is rejected when any resulting path already exists."
        ),
    )
    async def rename_term(
        domain_id: Annotated[UUID, Field(description="ID of the owning domain.")],
        term: Annotated[str, Field(description=TERM_REFERENCE)],
        new_name: Annotated[str, Field(description="New name of the term.")],
    ) -> OkResponse:
        """Rename a term."""
        with mcp_error_guard():
            await container.vocabulary_application().rename_term(
                domain_id,
                term,
                new_name,
            )
        return OkResponse()

    @mcp.tool(
        name="move_term",
        description=(
            "Move a draft or approved term under a new parent (null for the top level). "
            "Every descendant moves with it. A move under itself or one of its own "
            "descendants is rejected."
        ),
    )
    async def move_term(
        domain_id: Annotated[UUID, Field(description="ID of the owning domain.")],
        term: Annotated[str, Field(description=TERM_REFERENCE)],
        new_parent: Annotated[
            str | None,
            Field(
                description=(
                    f"New parent term reference, or null for the top level. {TERM_REFERENCE}"
                )
            ),
        ] = None,
    ) -> OkResponse:
        """Move a term."""
        with mcp_error_guard():
            await container.vocabulary_application().move_term(
                domain_id,
                term,
                new_parent,
            )
        return OkResponse()

    @mcp.tool(
        name="approve_term",
        description="Approve a draft term and freeze its content.",
    )
    async def approve_term(
        domain_id: Annotated[UUID, Field(description="ID of the owning domain.")],
        term: Annotated[str, Field(description=TERM_REFERENCE)],
        reviewer: Annotated[
            str | None,
            Field(description="Optional name of the reviewer."),
        ] = None,
    ) -> OkResponse:
        """Approve a term."""
        with mcp_error_guard():
            await container.vocabulary_application().approve_term(
                domain_id,
                term,
                reviewer,
            )
        return OkResponse()

    @mcp.tool(
        name="reopen_term",
        description="Reopen an approved term so its content can be edited again.",
    )
    async def reopen_term(
        domain_id: Annotated[UUID, Field(description="ID of the owning domain.")],
        term: Annotated[str, Field(description=TERM_REFERENCE)],
        reason: Annotated[
            str | None,
            Field(description="Optional reason for reopening the term."),
        ] = None,
    ) -> OkResponse:
        """Reopen a term."""
        with mcp_error_guard():
            await container.vocabulary_application().reopen_term(
                domain_id,
                term,
                reason,
            )
        return OkResponse()

    @mcp.tool(
        name="deprecate_term",
        description="Deprecate an approved term.",
    )
    async def deprecate_term(
        domain_id: Annotated[UUID, Field(description="ID of the owning domain.")],
        term: Annotated[str, Field(description=TERM_REFERENCE)],
        reason: Annotated[
            str | None,
            Field(description="Optional reason for deprecating the term."),
        ] = None,
    ) -> OkResponse:
        """Deprecate a term."""
        with mcp_error_guard():
            await container.vocabulary_application().deprecate_term(
                domain_id,
                term,
                reason,
            )
        return OkResponse()

    @mcp.tool(
        name="reactivate_term",
        description="Reactivate a deprecated term so its content can be edited again.",
    )
    async def reactivate_term(
        domain_id: Annotated[UUID, Field(description="ID of the owning domain.")],
        term: Annotated[str, Field(description=TERM_REFERENCE)],
        reason: Annotated[
            str | None,
            Field(description="Optional reason for reactivating the term."),
        ] = None,
    ) -> OkResponse:
        """Reactivate a term."""
        with mcp_error_guard():
            await container.vocabulary_application().reactivate_term(
                domain_id,
                term,
                reason,
            )
        return OkResponse()

    @mcp.tool(
        name="link_term",
        description=(
            "Link a draft term to a catalog object. target_kind is one of catalog, "
            "schema, table or field. For a field link target_id is the table id and "
            "field_name is the field name; for every other kind field_name must be "
            "omitted."
        ),
    )
    async def link_term(
        domain_id: Annotated[UUID, Field(description="ID of the owning domain.")],
        term: Annotated[str, Field(description=TERM_REFERENCE)],
        target_id: Annotated[
            UUID,
            Field(description="ID of the catalog, schema or table, or the owning table."),
        ],
        target_kind: Annotated[
            str,
            Field(description=("Kind of the target: " + ", ".join(sorted(TARGET_KINDS)) + ".")),
        ],
        field_name: Annotated[
            str,
            Field(description="Field name for field links, empty for every other kind."),
        ] = "",
    ) -> OkResponse:
        """Link a term to a catalog object."""
        with mcp_error_guard():
            await container.vocabulary_application().link_term(
                domain_id,
                term,
                target_id,
                target_kind,
                field_name,
            )
        return OkResponse()

    @mcp.tool(
        name="unlink_term",
        description=(
            "Remove a catalog link from a draft term. Use the same target_id, "
            "target_kind and field_name that were passed to link_term."
        ),
    )
    async def unlink_term(
        domain_id: Annotated[UUID, Field(description="ID of the owning domain.")],
        term: Annotated[str, Field(description=TERM_REFERENCE)],
        target_id: Annotated[UUID, Field(description="ID of the linked object.")],
        target_kind: Annotated[str, Field(description="Kind of the linked object.")],
        field_name: Annotated[
            str,
            Field(description="Field name for field links, empty for every other kind."),
        ] = "",
    ) -> OkResponse:
        """Remove a term link."""
        with mcp_error_guard():
            await container.vocabulary_application().unlink_term(
                domain_id,
                term,
                target_id,
                target_kind,
                field_name,
            )
        return OkResponse()

    @mcp.tool(
        name="discard_term",
        description="Discard a term and every descendant.",
        annotations={"destructiveHint": True},
    )
    async def discard_term(
        domain_id: Annotated[UUID, Field(description="ID of the owning domain.")],
        term: Annotated[str, Field(description=TERM_REFERENCE)],
    ) -> OkResponse:
        """Discard a term."""
        with mcp_error_guard():
            await container.vocabulary_application().discard_term(domain_id, term)
        return OkResponse()

    # ---- reads -----------------------------------------------------------

    @mcp.tool(
        name="list_domains",
        description="List all live vocabulary domains, ordered by name.",
        annotations={"readOnlyHint": True},
    )
    async def list_domains() -> list[DomainResponse]:
        """List domains."""
        rows = await container.vocabulary_view().list_domains()
        return [DomainResponse.from_row(row) for row in rows]

    @mcp.tool(
        name="get_domain",
        description="Return one domain, or null when it does not exist.",
        annotations={"readOnlyHint": True},
    )
    async def get_domain(
        domain_id: Annotated[UUID, Field(description="ID of the domain.")],
    ) -> DomainResponse | None:
        """Get a domain."""
        row = await container.vocabulary_view().get_domain(domain_id)
        return None if row is None else DomainResponse.from_row(row)

    @mcp.tool(
        name="list_terms",
        description="List the live terms of a domain, ordered by path.",
        annotations={"readOnlyHint": True},
    )
    async def list_terms(
        domain_id: Annotated[UUID, Field(description="ID of the owning domain.")],
        status: Annotated[
            str | None,
            Field(description="draft, approved, deprecated, or null for every status."),
        ] = None,
        limit: Annotated[int | None, Field(description="Maximum number of terms.")] = 50,
        offset: Annotated[int, Field(description="Number of terms to skip.")] = 0,
    ) -> list[TermSummaryResponse]:
        """List terms."""
        rows = await container.vocabulary_view().list_terms(
            domain_id,
            status=status,
            limit=limit,
            offset=offset,
        )
        return [TermSummaryResponse.from_row(row) for row in rows]

    @mcp.tool(
        name="get_term",
        description="Return one term with its aliases and catalog links, or null.",
        annotations={"readOnlyHint": True},
    )
    async def get_term(
        term_id: Annotated[UUID, Field(description="ID of the term.")],
    ) -> TermResponse | None:
        """Get a term."""
        view = container.vocabulary_view()
        row = await view.get_term(term_id)
        if row is None:
            return None
        return TermResponse.from_parts(
            row,
            await view.list_aliases(term_id),
            await resolve_term_links(
                container.catalog_view(),
                await view.list_links(term_id),
            ),
        )

    @mcp.tool(
        name="list_children",
        description="List the direct children of a term, or the top-level terms.",
        annotations={"readOnlyHint": True},
    )
    async def list_children(
        domain_id: Annotated[UUID, Field(description="ID of the owning domain.")],
        term: Annotated[
            str | None,
            Field(
                description=(f"Parent term reference, or null for the top level. {TERM_REFERENCE}")
            ),
        ] = None,
    ) -> list[TermSummaryResponse]:
        """List child terms."""
        view = container.vocabulary_view()
        parent_id: UUID | None = None
        if term is not None:
            term_id = await view.find_term_id(domain_id, term) or uuid_or_none(term)
            row = None if term_id is None else await view.get_term(term_id)
            if row is None or row.domain_id != domain_id:
                return []
            parent_id = row.term_id
        rows = await view.list_children(domain_id, parent_id)
        return [TermSummaryResponse.from_row(row) for row in rows]

    @mcp.tool(
        name="list_descendants",
        description="List every live descendant of a term, ordered by path.",
        annotations={"readOnlyHint": True},
    )
    async def list_descendants(
        domain_id: Annotated[UUID, Field(description="ID of the owning domain.")],
        term: Annotated[str, Field(description=TERM_REFERENCE)],
    ) -> list[TermSummaryResponse]:
        """List descendant terms."""
        view = container.vocabulary_view()
        term_id = await view.find_term_id(domain_id, term) or uuid_or_none(term)
        row = None if term_id is None else await view.get_term(term_id)
        if row is None or row.domain_id != domain_id:
            return []
        rows = await view.list_descendants(domain_id, row.term_id)
        return [TermSummaryResponse.from_row(row) for row in rows]

    @mcp.tool(
        name="search_terms",
        description=(
            "Find terms whose name, definition or alias contains the query, "
            "optionally restricted to a domain or status."
        ),
        annotations={"readOnlyHint": True},
    )
    async def search_terms(
        query: Annotated[str, Field(description="Substring to search for.")],
        domain_id: Annotated[
            UUID | None,
            Field(description="Only search this domain, or null for all."),
        ] = None,
        status: Annotated[
            str | None,
            Field(description="draft, approved, deprecated, or null for every status."),
        ] = None,
        limit: Annotated[int | None, Field(description="Maximum number of terms.")] = 50,
    ) -> list[TermSearchResultResponse]:
        """Search terms."""
        rows = await container.vocabulary_view().search_terms(
            query,
            domain_id=domain_id,
            status=status,
            limit=limit,
        )
        return [TermSearchResultResponse.from_row(row) for row in rows]

    @mcp.tool(
        name="list_terms_for_target",
        description="List the terms linked to exactly one catalog object.",
        annotations={"readOnlyHint": True},
    )
    async def list_terms_for_target(
        target_id: Annotated[UUID, Field(description="ID of the catalog object.")],
        target_kind: Annotated[
            str,
            Field(description="catalog, schema, table or field."),
        ],
        field_name: Annotated[
            str,
            Field(description="Field name for field links, empty for every other kind."),
        ] = "",
    ) -> list[TermSummaryResponse]:
        """List terms linked to a target."""
        rows = await container.vocabulary_view().terms_for_target(
            target_id,
            target_kind,
            field_name,
        )
        return [TermSummaryResponse.from_row(row) for row in rows]

    @mcp.tool(
        name="list_terms_for_table",
        description="List the terms linked to a table or to any of its fields.",
        annotations={"readOnlyHint": True},
    )
    async def list_terms_for_table(
        table_id: Annotated[UUID, Field(description="ID of the table.")],
    ) -> list[TermSummaryResponse]:
        """List terms linked to a table."""
        rows = await container.vocabulary_view().terms_for_table(table_id)
        return [TermSummaryResponse.from_row(row) for row in rows]

    @mcp.tool(
        name="list_terms_for_field",
        description="List the terms linked to one field of a table.",
        annotations={"readOnlyHint": True},
    )
    async def list_terms_for_field(
        table_id: Annotated[UUID, Field(description="ID of the owning table.")],
        field_name: Annotated[str, Field(description="Name of the field.")],
    ) -> list[TermSummaryResponse]:
        """List terms linked to a field."""
        rows = await container.vocabulary_view().terms_for_target(
            table_id,
            "field",
            field_name,
        )
        return [TermSummaryResponse.from_row(row) for row in rows]
