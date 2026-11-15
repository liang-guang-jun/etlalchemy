"""Application service exposing the vocabulary use cases."""

from __future__ import annotations

from uuid import UUID

import structlog
from eventsourcing.utils import EnvType

from etlalchemy._vendor.eventsourcing.asyncio.application import AsyncApplication
from etlalchemy.catalog.projection.view import CatalogView
from etlalchemy.shared.logging import get_logger
from etlalchemy.vocabulary.aggregates.domain import Domain
from etlalchemy.vocabulary.aggregates.errors import (
    CycleError,
    DuplicateAliasError,
    InvalidAliasError,
    InvalidLinkError,
    UnknownLinkError,
    UnknownParentError,
    UnknownTermError,
)
from etlalchemy.vocabulary.aggregates.term import Term
from etlalchemy.vocabulary.aggregates.types import normalise_color


def _parse_uuid(value: UUID | str) -> UUID | None:
    """Returns the value as a :class:`UUID`, or ``None`` when it is not one."""
    if isinstance(value, UUID):
        return value
    try:
        return UUID(value)
    except ValueError:
        return None


def _normalise_aliases(aliases: list[str] | tuple[str, ...] | None) -> tuple[str, ...]:
    """Trims the aliases and rejects blank or repeated entries."""
    normalised = [alias.strip() for alias in aliases or ()]
    if any(not alias for alias in normalised):
        msg = "aliases must not be blank"
        raise InvalidAliasError(msg)
    if len(set(normalised)) != len(normalised):
        msg = "aliases must not repeat"
        raise DuplicateAliasError(msg)
    return tuple(normalised)


def _join_path(parent_path: str, name: str) -> str:
    """Returns the path of a child term under ``parent_path``."""
    return f"{parent_path}/{name}" if parent_path else name


class VocabularyApplication(AsyncApplication[UUID]):
    """Application service for the vocabulary context.

    Each use case loads the domain and the terms it needs, applies one command per
    aggregate and saves the resulting events in a single unit of work.

    A term is addressed by its full path (``Revenue/ARR``) or by its id; the ids
    the create use cases return therefore keep working after a rename. Renaming or
    moving a term repaths every descendant in the same unit of work, so the size
    of that transaction grows with the subtree: a root rename in a tree with a
    thousand descendants writes a thousand events.
    """

    name = "vocabulary_application"
    """Application name; the eventsourcing factories derive table names from it."""

    def __init__(self, catalog_view: CatalogView, env: EnvType | None = None) -> None:
        """Wires the catalog read model used to validate term links."""
        super().__init__(env=env)
        self._catalog_view = catalog_view
        self._log: structlog.stdlib.BoundLogger = get_logger("vocabulary.application")

    # -- domain -------------------------------------------------------------

    async def create_domain(self, name: str, description: str = "") -> UUID:
        """Creates a domain and returns its ID."""
        self._log.info("vocabulary.domain.create start", name=name)
        domain = Domain(name=name, description=description)
        await self.save(domain)
        self._log.info("vocabulary.domain.create done", domain_id=str(domain.id))
        return domain.id

    async def get_domain(self, domain_id: UUID) -> Domain:
        """Returns the domain with the given ID."""
        self._log.debug("vocabulary.domain.get start", domain_id=str(domain_id))
        domain = await self._domain(domain_id)
        self._log.debug("vocabulary.domain.get done", domain_id=str(domain.id), name=domain.name)
        return domain

    async def change_domain(
        self,
        domain_id: UUID,
        name: str | None = None,
        description: str | None = None,
    ) -> None:
        """Changes the name and/or description of a domain."""
        self._log.info(
            "vocabulary.domain.change start",
            domain_id=str(domain_id),
            name=name,
            changes_description=description is not None,
        )
        domain = await self._domain(domain_id)
        domain.change(name, description)
        await self.save(domain)
        self._log.info("vocabulary.domain.change done", domain_id=str(domain_id))

    async def discard_domain(self, domain_id: UUID) -> None:
        """Marks a domain, its terms and their children as discarded in the read model."""
        self._log.info("vocabulary.domain.discard start", domain_id=str(domain_id))
        domain = await self._domain(domain_id)
        domain.discard()
        await self.save(domain)
        self._log.info("vocabulary.domain.discard done", domain_id=str(domain_id))

    # -- terms --------------------------------------------------------------

    async def create_term(
        self,
        domain_id: UUID,
        term_name: str,
        definition: str,
        aliases: list[str] | None = None,
        parent: UUID | str | None = None,
        color: str = "",
    ) -> UUID:
        """Creates a draft term under an optional parent and returns its ID."""
        self._log.info(
            "vocabulary.term.create start",
            domain_id=str(domain_id),
            term=term_name,
            parent=str(parent),
            aliases=len(aliases or ()),
            color=color or None,
        )
        domain = await self._domain(domain_id)
        parent_id: UUID | None = None
        parent_path = ""
        if parent is not None:
            parent_term = await self._parent_term(domain, parent)
            parent_id = parent_term.id
            parent_path = parent_term.path
        path = _join_path(parent_path, term_name)
        term = Term(
            domain_id=domain_id,
            name=term_name,
            definition=definition,
            aliases=_normalise_aliases(aliases),
            parent_id=parent_id,
            path=path,
            color=normalise_color(color),
        )
        domain.register_term(path, term.id)
        await self.save(domain, term)
        self._log.info("vocabulary.term.create done", term_id=str(term.id), path=path)
        return term.id

    async def get_term(self, domain_id: UUID, term: UUID | str) -> Term:
        """Returns the term referenced by its path or id in the domain."""
        self._log.debug(
            "vocabulary.term.get start",
            domain_id=str(domain_id),
            term=str(term),
        )
        loaded = await self._term(await self._domain(domain_id), term)
        self._log.debug("vocabulary.term.get done", term_id=str(loaded.id), path=loaded.path)
        return loaded

    async def change_term_definition(
        self,
        domain_id: UUID,
        term: UUID | str,
        definition: str,
    ) -> None:
        """Replaces the definition of a draft term."""
        self._log.info(
            "vocabulary.term.definition.change start",
            domain_id=str(domain_id),
            term=str(term),
        )
        loaded = await self.get_term(domain_id, term)
        loaded.change_definition(definition)
        await self.save(loaded)
        self._log.info("vocabulary.term.definition.change done", term_id=str(loaded.id))

    async def change_term_color(
        self,
        domain_id: UUID,
        term: UUID | str,
        color: str,
    ) -> None:
        """Sets the presentation colour of a term."""
        self._log.info(
            "vocabulary.term.color.change start",
            domain_id=str(domain_id),
            term=str(term),
            color=color or None,
        )
        loaded = await self.get_term(domain_id, term)
        loaded.change_color(normalise_color(color))
        await self.save(loaded)
        self._log.info("vocabulary.term.color.change done", term_id=str(loaded.id))

    async def add_term_alias(
        self,
        domain_id: UUID,
        term: UUID | str,
        alias: str,
    ) -> None:
        """Adds an alias to a draft term."""
        self._log.info(
            "vocabulary.term.alias.add start",
            domain_id=str(domain_id),
            term=str(term),
            alias=alias,
        )
        loaded = await self.get_term(domain_id, term)
        loaded.add_alias(alias.strip())
        await self.save(loaded)
        self._log.info("vocabulary.term.alias.add done", term_id=str(loaded.id))

    async def remove_term_alias(
        self,
        domain_id: UUID,
        term: UUID | str,
        alias: str,
    ) -> None:
        """Removes an alias from a draft term."""
        self._log.info(
            "vocabulary.term.alias.remove start",
            domain_id=str(domain_id),
            term=str(term),
            alias=alias,
        )
        loaded = await self.get_term(domain_id, term)
        loaded.remove_alias(alias.strip())
        await self.save(loaded)
        self._log.info("vocabulary.term.alias.remove done", term_id=str(loaded.id))

    async def rename_term(
        self,
        domain_id: UUID,
        term: UUID | str,
        new_name: str,
    ) -> None:
        """Renames a term and repaths every descendant in one unit of work."""
        self._log.info(
            "vocabulary.term.rename start",
            domain_id=str(domain_id),
            term=str(term),
            new_name=new_name,
        )
        domain = await self._domain(domain_id)
        loaded = await self._term(domain, term)
        old_path = loaded.path
        new_path = _join_path(old_path.rpartition("/")[0], new_name)
        domain.repath_term(loaded.id, new_path)
        loaded.rename(new_name, new_path)
        updated = [loaded]
        updated.extend(await self._cascade(domain, loaded.id, old_path, new_path))
        await self.save(domain, *updated)
        self._log.info(
            "vocabulary.term.rename done",
            term_id=str(loaded.id),
            old_path=old_path,
            new_path=new_path,
            descendants=len(updated) - 1,
        )

    async def move_term(
        self,
        domain_id: UUID,
        term: UUID | str,
        new_parent: UUID | str | None = None,
    ) -> None:
        """Moves a term under another parent and repaths every descendant."""
        self._log.info(
            "vocabulary.term.move start",
            domain_id=str(domain_id),
            term=str(term),
            new_parent=str(new_parent),
        )
        domain = await self._domain(domain_id)
        loaded = await self._term(domain, term)
        new_parent_id: UUID | None = None
        new_parent_path = ""
        if new_parent is not None:
            parent_term = await self._parent_term(domain, new_parent)
            # Names never contain '/', so a path prefix means a descendant.
            if parent_term.id == loaded.id or parent_term.path.startswith(f"{loaded.path}/"):
                msg = (
                    f"Cannot move term {loaded.path!r} under its own descendant "
                    f"{parent_term.path!r}"
                )
                raise CycleError(msg)
            new_parent_id = parent_term.id
            new_parent_path = parent_term.path
        old_path = loaded.path
        new_path = _join_path(new_parent_path, loaded.name)
        domain.repath_term(loaded.id, new_path)
        loaded.move(new_parent_id, new_path)
        updated = [loaded]
        updated.extend(await self._cascade(domain, loaded.id, old_path, new_path))
        await self.save(domain, *updated)
        self._log.info(
            "vocabulary.term.move done",
            term_id=str(loaded.id),
            old_path=old_path,
            new_path=new_path,
            descendants=len(updated) - 1,
        )

    async def approve_term(
        self,
        domain_id: UUID,
        term: UUID | str,
        reviewer: str | None = None,
    ) -> None:
        """Approves a draft term."""
        self._log.info(
            "vocabulary.term.approve start",
            domain_id=str(domain_id),
            term=str(term),
        )
        loaded = await self.get_term(domain_id, term)
        loaded.approve(reviewer)
        await self.save(loaded)
        self._log.info("vocabulary.term.approve done", term_id=str(loaded.id))

    async def reopen_term(
        self,
        domain_id: UUID,
        term: UUID | str,
        reason: str | None = None,
    ) -> None:
        """Reopens an approved term for editing."""
        self._log.info(
            "vocabulary.term.reopen start",
            domain_id=str(domain_id),
            term=str(term),
        )
        loaded = await self.get_term(domain_id, term)
        loaded.reopen(reason)
        await self.save(loaded)
        self._log.info("vocabulary.term.reopen done", term_id=str(loaded.id))

    async def deprecate_term(
        self,
        domain_id: UUID,
        term: UUID | str,
        reason: str | None = None,
    ) -> None:
        """Deprecates an approved term."""
        self._log.info(
            "vocabulary.term.deprecate start",
            domain_id=str(domain_id),
            term=str(term),
        )
        loaded = await self.get_term(domain_id, term)
        loaded.deprecate(reason)
        await self.save(loaded)
        self._log.info("vocabulary.term.deprecate done", term_id=str(loaded.id))

    async def reactivate_term(
        self,
        domain_id: UUID,
        term: UUID | str,
        reason: str | None = None,
    ) -> None:
        """Reactivates a deprecated term for editing."""
        self._log.info(
            "vocabulary.term.reactivate start",
            domain_id=str(domain_id),
            term=str(term),
        )
        loaded = await self.get_term(domain_id, term)
        loaded.reactivate(reason)
        await self.save(loaded)
        self._log.info("vocabulary.term.reactivate done", term_id=str(loaded.id))

    async def link_term(
        self,
        domain_id: UUID,
        term: UUID | str,
        target_id: UUID,
        target_kind: str,
        field_name: str = "",
    ) -> None:
        """Links a draft term to an existing catalog object."""
        self._log.info(
            "vocabulary.term.link start",
            domain_id=str(domain_id),
            term=str(term),
            target_id=str(target_id),
            target_kind=target_kind,
            field_name=field_name,
        )
        loaded = await self.get_term(domain_id, term)
        await self._validate_link_target(target_id, target_kind, field_name)
        loaded.link(target_id, target_kind, field_name)
        await self.save(loaded)
        self._log.info("vocabulary.term.link done", term_id=str(loaded.id))

    async def unlink_term(
        self,
        domain_id: UUID,
        term: UUID | str,
        target_id: UUID,
        target_kind: str,
        field_name: str = "",
    ) -> None:
        """Removes a catalog link from a draft term."""
        self._log.info(
            "vocabulary.term.unlink start",
            domain_id=str(domain_id),
            term=str(term),
            target_id=str(target_id),
            target_kind=target_kind,
            field_name=field_name,
        )
        loaded = await self.get_term(domain_id, term)
        loaded.unlink(target_id, target_kind, field_name)
        await self.save(loaded)
        self._log.info("vocabulary.term.unlink done", term_id=str(loaded.id))

    async def discard_term(self, domain_id: UUID, term: UUID | str) -> None:
        """Discards a term and every descendant in one unit of work."""
        self._log.info(
            "vocabulary.term.discard start",
            domain_id=str(domain_id),
            term=str(term),
        )
        domain = await self._domain(domain_id)
        loaded = await self._term(domain, term)
        snapshot = self._descendant_snapshot(domain, loaded.path)
        loaded.discard()
        domain.unregister_term(loaded.path)
        updated = [loaded]
        for old_child_path, child_id in snapshot:
            child: Term = await self.repository.get(child_id)
            assert isinstance(child, Term)
            child.discard()
            domain.unregister_term(old_child_path)
            updated.append(child)
        await self.save(domain, *updated)
        self._log.info(
            "vocabulary.term.discard done",
            term_id=str(loaded.id),
            descendants=len(updated) - 1,
        )

    # -- internals ----------------------------------------------------------

    async def _cascade(
        self,
        domain: Domain,
        exclude_id: UUID,
        old_path: str,
        new_path: str,
    ) -> list[Term]:
        """Repaths every descendant of a renamed or moved term.

        ``exclude_id`` is the term that was already repathed; it is skipped even
        when the new path still falls under the old prefix.
        """
        updated: list[Term] = []
        for old_child_path, child_id in self._descendant_snapshot(domain, old_path):
            if child_id == exclude_id:
                continue
            child_new_path = new_path + old_child_path[len(old_path) :]
            domain.repath_term(child_id, child_new_path)
            child: Term = await self.repository.get(child_id)
            assert isinstance(child, Term)
            child.repath(child_new_path)
            updated.append(child)
        return updated

    @staticmethod
    def _descendant_snapshot(domain: Domain, path: str) -> list[tuple[str, UUID]]:
        """Returns the registered descendants of a path, parents before children."""
        prefix = f"{path}/"
        return sorted(
            (child_path, child_id)
            for child_path, child_id in domain.terms.items()
            if child_path.startswith(prefix)
        )

    async def _validate_link_target(
        self,
        target_id: UUID,
        target_kind: str,
        field_name: str,
    ) -> None:
        """Rejects a link whose catalog target does not exist."""
        if target_kind == "catalog":
            if await self._catalog_view.get_catalog(target_id) is None:
                msg = f"Catalog {target_id} does not exist"
                raise UnknownLinkError(msg)
        elif target_kind == "schema":
            if await self._catalog_view.get_schema(target_id) is None:
                msg = f"Schema {target_id} does not exist"
                raise UnknownLinkError(msg)
        elif target_kind == "table":
            if await self._catalog_view.get_table(target_id) is None:
                msg = f"Table {target_id} does not exist"
                raise UnknownLinkError(msg)
        elif target_kind == "field":
            table = await self._catalog_view.get_table(target_id)
            if table is None:
                msg = f"Table {target_id} does not exist"
                raise UnknownLinkError(msg)
            names = {field.name for field in await self._catalog_view.list_fields(target_id)}
            if field_name not in names:
                msg = f"Field {field_name!r} does not exist in table {target_id}"
                raise UnknownLinkError(msg)
        else:
            msg = f"unknown target_kind: {target_kind!r}"
            raise InvalidLinkError(msg)

    async def _domain(self, domain_id: UUID) -> Domain:
        """Returns the domain with the given ID."""
        domain: Domain = await self.repository.get(domain_id)
        assert isinstance(domain, Domain)
        return domain

    async def _term(self, domain: Domain, term: UUID | str) -> Term:
        """Loads the term referenced by its path or id in the domain."""
        registered = domain.terms.get(term) if isinstance(term, str) else None
        term_id = registered if registered is not None else _parse_uuid(term)
        if term_id is None or not domain.has_term(term_id):
            self._log.debug(
                "vocabulary.term.not_found",
                domain_id=str(domain.id),
                term=str(term),
            )
            msg = f"Term {term!r} does not exist in domain {domain.name!r}"
            raise UnknownTermError(msg)
        loaded: Term = await self.repository.get(term_id)
        assert isinstance(loaded, Term)
        return loaded

    async def _parent_term(self, domain: Domain, parent: UUID | str) -> Term:
        """Loads an explicit parent and reports a missing one as such."""
        try:
            return await self._term(domain, parent)
        except UnknownTermError as exc:
            msg = f"Parent term {parent!r} does not exist in domain {domain.name!r}"
            raise UnknownParentError(msg) from exc
