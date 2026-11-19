"""HTTP routes exposing the vocabulary context."""

from __future__ import annotations

from uuid import UUID

from dependency_injector.wiring import Provide, inject
from eventsourcing.application import AggregateNotFoundError
from eventsourcing.persistence import RecordConflictError
from fastapi import APIRouter, Depends, FastAPI, HTTPException
from pydantic import BaseModel, Field

from etlalchemy.app.api.errors import install_exception_handlers
from etlalchemy.app.bootstrap import Container
from etlalchemy.app.schemas.common import OkResponse
from etlalchemy.app.schemas.vocabulary import (
    DomainCreatedResponse,
    DomainResponse,
    TermCreatedResponse,
    TermResponse,
    TermSearchResultResponse,
    TermSummaryResponse,
)
from etlalchemy.catalog.projection.view import CatalogView
from etlalchemy.shared.utils import uuid_or_none
from etlalchemy.vocabulary.aggregates.errors import (
    InvalidColorError,
    UnknownDomainError,
    UnknownLinkError,
    UnknownParentError,
    UnknownTermError,
    VocabularyError,
)
from etlalchemy.vocabulary.application import VocabularyApplication
from etlalchemy.vocabulary.links import resolve_term_links
from etlalchemy.vocabulary.projection.view import TermRow, VocabularyView

router = APIRouter(prefix="/vocabulary", tags=["vocabulary"])

CONFLICT_ERRORS = (VocabularyError, RecordConflictError)
NOT_FOUND_ERRORS = (
    UnknownDomainError,
    UnknownTermError,
    UnknownParentError,
    UnknownLinkError,
    AggregateNotFoundError,
)


def add_exception_handlers(app: FastAPI) -> None:
    """Maps vocabulary errors to HTTP responses."""
    # Starlette resolves handlers through the MRO, so the exact class wins over
    # the VocabularyError base: a malformed colour is a bad request, not a conflict.
    install_exception_handlers(
        app,
        conflict=CONFLICT_ERRORS,
        not_found=NOT_FOUND_ERRORS,
        bad_request=(InvalidColorError, ValueError),
    )


class DomainCreate(BaseModel):
    """Body of ``POST /vocabulary/domains``."""

    name: str
    """Name of the new domain."""
    description: str = ""
    """Free-form description of the new domain."""


class DomainPatch(BaseModel):
    """Body of ``PATCH /vocabulary/domains/{domain_id}``."""

    name: str | None = None
    """New name, or ``None`` to keep the current one."""
    description: str | None = None
    """New description, or ``None`` to keep the current one."""


class TermCreate(BaseModel):
    """Body of ``POST /vocabulary/domains/{domain_id}/terms``."""

    name: str
    """Name of the new term."""
    definition: str
    """Initial definition of the new term."""
    aliases: list[str] = Field(default_factory=list)
    """Initial aliases of the new term."""
    parent: str | None = None
    """Parent term id or full path, or ``None`` for a top-level term."""
    color: str = ""
    """Initial colour as ``#rrggbb``, or an empty string for none."""


class TermPatch(BaseModel):
    """Body of ``PATCH .../terms/{term_id}``.

    ``name`` is accepted for drafts and approved terms, ``color`` in every live
    status; ``definition`` and the alias lists only for drafts. The commands are
    applied in the order color, definition, aliases_add, aliases_remove, name.
    """

    name: str | None = None
    """New name, or ``None`` to keep the current one."""
    definition: str | None = None
    """New definition, or ``None`` to keep the current one."""
    aliases_add: list[str] | None = None
    """Aliases to add."""
    aliases_remove: list[str] | None = None
    """Aliases to remove."""
    color: str | None = None
    """New colour as ``#rrggbb``, or an empty string to clear it."""

    def is_empty(self) -> bool:
        """Returns whether the body changes nothing."""
        return (
            self.name is None
            and self.definition is None
            and not self.aliases_add
            and not self.aliases_remove
            and self.color is None
        )


class TermMove(BaseModel):
    """Body of ``POST .../terms/{term_id}/move``."""

    new_parent: str | None = None
    """New parent term id or full path, or ``None`` to move to the top level."""


async def _term_row(
    view: VocabularyView,
    domain_id: UUID,
    term_id: UUID,
) -> TermRow:
    """Returns the term, rejecting an id owned by another domain."""
    row = await view.get_term(term_id)
    if row is None or row.domain_id != domain_id:
        msg = f"Term {term_id} does not exist in domain {domain_id}"
        raise UnknownTermError(msg)
    return row


async def _parent_id(
    view: VocabularyView,
    domain_id: UUID,
    parent: str | None,
) -> UUID | None:
    """Resolves a parent id or path to its id, or ``None`` for the top level."""
    if parent is None:
        return None
    term_id = await view.find_term_id(domain_id, parent) or uuid_or_none(parent)
    row = None if term_id is None else await view.get_term(term_id)
    if row is None or row.domain_id != domain_id:
        msg = f"Parent term {parent!r} does not exist in domain {domain_id}"
        raise UnknownParentError(msg)
    return row.term_id


async def _term_response(
    view: VocabularyView,
    catalog: CatalogView,
    row: TermRow,
) -> TermResponse:
    """Composes a term with its aliases and resolved catalog links."""
    return TermResponse.from_parts(
        row,
        await view.list_aliases(row.term_id),
        await resolve_term_links(catalog, await view.list_links(row.term_id)),
    )


# -- domain -----------------------------------------------------------------


@router.post("/domains", status_code=201, response_model=DomainCreatedResponse)
@inject
async def create_domain(
    body: DomainCreate,
    application: VocabularyApplication = Depends(  # noqa: B008
        Provide[Container.vocabulary_application]
    ),
) -> DomainCreatedResponse:
    """Creates a domain and returns its ID."""
    domain_id = await application.create_domain(body.name, body.description)
    return DomainCreatedResponse(domain_id=domain_id)


@router.get("/domains", response_model=list[DomainResponse])
@inject
async def list_domains(
    view: VocabularyView = Depends(Provide[Container.vocabulary_view]),  # noqa: B008
) -> list[DomainResponse]:
    """Lists all live domains from the read model."""
    return [DomainResponse.from_row(row) for row in await view.list_domains()]


@router.get("/domains/{domain_id}", response_model=DomainResponse)
@inject
async def get_domain(
    domain_id: UUID,
    view: VocabularyView = Depends(Provide[Container.vocabulary_view]),  # noqa: B008
) -> DomainResponse:
    """Returns one domain from the read model."""
    row = await view.get_domain(domain_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Domain {domain_id} not found")
    return DomainResponse.from_row(row)


@router.patch("/domains/{domain_id}", response_model=OkResponse)
@inject
async def change_domain(
    domain_id: UUID,
    body: DomainPatch,
    application: VocabularyApplication = Depends(  # noqa: B008
        Provide[Container.vocabulary_application]
    ),
) -> OkResponse:
    """Changes the name and/or description of a domain."""
    await application.change_domain(domain_id, body.name, body.description)
    return OkResponse()


@router.delete("/domains/{domain_id}", status_code=204)
@inject
async def discard_domain(
    domain_id: UUID,
    application: VocabularyApplication = Depends(  # noqa: B008
        Provide[Container.vocabulary_application]
    ),
) -> None:
    """Discards a domain together with its terms."""
    await application.discard_domain(domain_id)


# -- terms ------------------------------------------------------------------


@router.post(
    "/domains/{domain_id}/terms",
    status_code=201,
    response_model=TermCreatedResponse,
)
@inject
async def create_term(
    domain_id: UUID,
    body: TermCreate,
    application: VocabularyApplication = Depends(  # noqa: B008
        Provide[Container.vocabulary_application]
    ),
) -> TermCreatedResponse:
    """Creates a term under an optional parent and returns its ID."""
    term_id = await application.create_term(
        domain_id,
        body.name,
        body.definition,
        body.aliases,
        body.parent,
        body.color,
    )
    return TermCreatedResponse(term_id=term_id)


@router.get(
    "/domains/{domain_id}/terms",
    response_model=list[TermSummaryResponse],
)
@inject
async def list_terms(
    domain_id: UUID,
    status: str | None = None,
    limit: int | None = None,
    offset: int = 0,
    view: VocabularyView = Depends(Provide[Container.vocabulary_view]),  # noqa: B008
) -> list[TermSummaryResponse]:
    """Lists the live terms of a domain, ordered by path."""
    if await view.get_domain(domain_id) is None:
        raise UnknownDomainError(f"Domain {domain_id} is not known")
    terms = await view.list_terms(domain_id, status=status, limit=limit, offset=offset)
    return [TermSummaryResponse.from_row(term) for term in terms]


@router.get(
    "/domains/{domain_id}/children",
    response_model=list[TermSummaryResponse],
)
@inject
async def list_children(
    domain_id: UUID,
    parent: str | None = None,
    view: VocabularyView = Depends(Provide[Container.vocabulary_view]),  # noqa: B008
) -> list[TermSummaryResponse]:
    """Lists the direct children of a term, or the top-level terms."""
    if await view.get_domain(domain_id) is None:
        raise UnknownDomainError(f"Domain {domain_id} is not known")
    parent_id = await _parent_id(view, domain_id, parent)
    rows = await view.list_children(domain_id, parent_id)
    return [TermSummaryResponse.from_row(row) for row in rows]


@router.get(
    "/domains/{domain_id}/terms/{term_id}",
    response_model=TermResponse,
)
@inject
async def get_term(
    domain_id: UUID,
    term_id: UUID,
    view: VocabularyView = Depends(Provide[Container.vocabulary_view]),  # noqa: B008
    catalog: CatalogView = Depends(Provide[Container.catalog_view]),  # noqa: B008
) -> TermResponse:
    """Returns a term with its aliases and catalog links."""
    return await _term_response(
        view,
        catalog,
        await _term_row(view, domain_id, term_id),
    )


@router.patch(
    "/domains/{domain_id}/terms/{term_id}",
    response_model=OkResponse,
)
@inject
async def patch_term(
    domain_id: UUID,
    term_id: UUID,
    body: TermPatch,
    application: VocabularyApplication = Depends(  # noqa: B008
        Provide[Container.vocabulary_application]
    ),
    view: VocabularyView = Depends(Provide[Container.vocabulary_view]),  # noqa: B008
) -> OkResponse:
    """Changes the content, aliases, name or colour of a term."""
    if body.is_empty():
        raise ValueError("patch body must change at least one attribute")
    await _term_row(view, domain_id, term_id)
    if body.color is not None:
        await application.change_term_color(domain_id, term_id, body.color)
    if body.definition is not None:
        await application.change_term_definition(domain_id, term_id, body.definition)
    for alias in body.aliases_add or []:
        await application.add_term_alias(domain_id, term_id, alias)
    for alias in body.aliases_remove or []:
        await application.remove_term_alias(domain_id, term_id, alias)
    if body.name is not None:
        await application.rename_term(domain_id, term_id, body.name)
    return OkResponse()


@router.post(
    "/domains/{domain_id}/terms/{term_id}/move",
    response_model=OkResponse,
)
@inject
async def move_term(
    domain_id: UUID,
    term_id: UUID,
    body: TermMove,
    application: VocabularyApplication = Depends(  # noqa: B008
        Provide[Container.vocabulary_application]
    ),
    view: VocabularyView = Depends(Provide[Container.vocabulary_view]),  # noqa: B008
) -> OkResponse:
    """Moves a term under another parent."""
    await _term_row(view, domain_id, term_id)
    await application.move_term(domain_id, term_id, body.new_parent)
    return OkResponse()


@router.delete("/domains/{domain_id}/terms/{term_id}", status_code=204)
@inject
async def discard_term(
    domain_id: UUID,
    term_id: UUID,
    application: VocabularyApplication = Depends(  # noqa: B008
        Provide[Container.vocabulary_application]
    ),
) -> None:
    """Discards a term and its descendants."""
    await application.discard_term(domain_id, term_id)


@router.post(
    "/domains/{domain_id}/terms/{term_id}/approve",
    response_model=OkResponse,
)
@inject
async def approve_term(
    domain_id: UUID,
    term_id: UUID,
    reviewer: str | None = None,
    application: VocabularyApplication = Depends(  # noqa: B008
        Provide[Container.vocabulary_application]
    ),
) -> OkResponse:
    """Approves a draft term."""
    await application.approve_term(domain_id, term_id, reviewer)
    return OkResponse()


@router.post(
    "/domains/{domain_id}/terms/{term_id}/reopen",
    response_model=OkResponse,
)
@inject
async def reopen_term(
    domain_id: UUID,
    term_id: UUID,
    reason: str | None = None,
    application: VocabularyApplication = Depends(  # noqa: B008
        Provide[Container.vocabulary_application]
    ),
) -> OkResponse:
    """Reopens an approved term for editing."""
    await application.reopen_term(domain_id, term_id, reason)
    return OkResponse()


@router.post(
    "/domains/{domain_id}/terms/{term_id}/deprecate",
    response_model=OkResponse,
)
@inject
async def deprecate_term(
    domain_id: UUID,
    term_id: UUID,
    reason: str | None = None,
    application: VocabularyApplication = Depends(  # noqa: B008
        Provide[Container.vocabulary_application]
    ),
) -> OkResponse:
    """Deprecates an approved term."""
    await application.deprecate_term(domain_id, term_id, reason)
    return OkResponse()


@router.post(
    "/domains/{domain_id}/terms/{term_id}/reactivate",
    response_model=OkResponse,
)
@inject
async def reactivate_term(
    domain_id: UUID,
    term_id: UUID,
    reason: str | None = None,
    application: VocabularyApplication = Depends(  # noqa: B008
        Provide[Container.vocabulary_application]
    ),
) -> OkResponse:
    """Reactivates a deprecated term for editing."""
    await application.reactivate_term(domain_id, term_id, reason)
    return OkResponse()


@router.post("/domains/{domain_id}/terms/{term_id}/links", status_code=204)
@inject
async def link_term(
    domain_id: UUID,
    term_id: UUID,
    target_id: UUID,
    target_kind: str,
    field_name: str = "",
    application: VocabularyApplication = Depends(  # noqa: B008
        Provide[Container.vocabulary_application]
    ),
) -> None:
    """Links a draft term to a catalog object or to a field of a table."""
    await application.link_term(
        domain_id,
        term_id,
        target_id,
        target_kind,
        field_name,
    )


@router.delete("/domains/{domain_id}/terms/{term_id}/links", status_code=204)
@inject
async def unlink_term(
    domain_id: UUID,
    term_id: UUID,
    target_id: UUID,
    target_kind: str,
    field_name: str = "",
    application: VocabularyApplication = Depends(  # noqa: B008
        Provide[Container.vocabulary_application]
    ),
) -> None:
    """Removes a catalog link from a draft term."""
    await application.unlink_term(
        domain_id,
        term_id,
        target_id,
        target_kind,
        field_name,
    )


@router.get(
    "/domains/{domain_id}/terms/{term_id}/descendants",
    response_model=list[TermSummaryResponse],
)
@inject
async def list_descendants(
    domain_id: UUID,
    term_id: UUID,
    view: VocabularyView = Depends(Provide[Container.vocabulary_view]),  # noqa: B008
) -> list[TermSummaryResponse]:
    """Lists every live descendant of a term."""
    await _term_row(view, domain_id, term_id)
    rows = await view.list_descendants(domain_id, term_id)
    return [TermSummaryResponse.from_row(row) for row in rows]


# -- reverse lookups --------------------------------------------------------


@router.get("/terms-for-target", response_model=list[TermSummaryResponse])
@inject
async def list_terms_for_target(
    target_id: UUID,
    target_kind: str,
    field_name: str = "",
    view: VocabularyView = Depends(Provide[Container.vocabulary_view]),  # noqa: B008
) -> list[TermSummaryResponse]:
    """Lists the live terms linked to exactly one catalog object."""
    rows = await view.terms_for_target(target_id, target_kind, field_name)
    return [TermSummaryResponse.from_row(row) for row in rows]


@router.get("/terms-for-table", response_model=list[TermSummaryResponse])
@inject
async def list_terms_for_table(
    table_id: UUID,
    view: VocabularyView = Depends(Provide[Container.vocabulary_view]),  # noqa: B008
) -> list[TermSummaryResponse]:
    """Lists the live terms linked to a table or to any of its fields."""
    rows = await view.terms_for_table(table_id)
    return [TermSummaryResponse.from_row(row) for row in rows]


@router.get("/terms-for-field", response_model=list[TermSummaryResponse])
@inject
async def list_terms_for_field(
    table_id: UUID,
    field_name: str,
    view: VocabularyView = Depends(Provide[Container.vocabulary_view]),  # noqa: B008
) -> list[TermSummaryResponse]:
    """Lists the live terms linked to one field of a table."""
    rows = await view.terms_for_target(table_id, "field", field_name)
    return [TermSummaryResponse.from_row(row) for row in rows]


# -- search -----------------------------------------------------------------


@router.get("/search", response_model=list[TermSearchResultResponse])
@inject
async def search_terms(
    q: str,
    domain_id: UUID | None = None,
    status: str | None = None,
    limit: int | None = None,
    view: VocabularyView = Depends(Provide[Container.vocabulary_view]),  # noqa: B008
) -> list[TermSearchResultResponse]:
    """Finds terms by name, definition or alias."""
    results = await view.search_terms(
        q,
        domain_id=domain_id,
        status=status,
        limit=limit,
    )
    return [TermSearchResultResponse.from_row(row) for row in results]
