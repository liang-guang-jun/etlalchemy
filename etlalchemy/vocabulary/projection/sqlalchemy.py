"""Asynchronous SQLAlchemy implementation of the vocabulary read model.

SQLAlchemy Core builds the table definitions and the DML statements; they are
executed on the async engine of
:class:`~eventsourcing.asyncio.sqlalchemy.AsyncSQLAlchemyDatastore`, so the view
change and its tracking record still share one transaction. The same class serves
SQLite (``aiosqlite``) and PostgreSQL (``psycopg``); only the upsert dialect
differs.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import and_, delete, func, or_, select, update

from etlalchemy.shared.persistence import AsyncCoreView, ensure_column, utc_now
from etlalchemy.vocabulary.projection.tables import (
    metadata,
    vocabulary_domains,
    vocabulary_term_aliases,
    vocabulary_term_links,
    vocabulary_terms,
)
from etlalchemy.vocabulary.projection.view import (
    DomainRow,
    TermLinkRow,
    TermRow,
    TermSearchResult,
    VocabularyView,
    as_uuid,
)

if TYPE_CHECKING:
    from eventsourcing.persistence import Tracking


def _escape_like(value: str) -> str:
    """Escapes the LIKE wildcards in a path prefix."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


class SQLAlchemyVocabularyView(AsyncCoreView, VocabularyView):
    """Asynchronous materialised view of the vocabulary aggregates."""

    view_metadata = metadata

    async def migrate(self, conn: Any) -> None:
        """Adds ``color`` to a term table created before terms had a colour."""
        await ensure_column(
            conn,
            self.datastore.dialect_name,
            "vocabulary_terms",
            "color",
            "TEXT NOT NULL DEFAULT ''",
        )

    # -- domain -------------------------------------------------------------

    async def register_domain(
        self,
        domain_id: UUID,
        name: str,
        description: str,
        tracking: Tracking,
    ) -> None:
        """Registers a domain in the view."""
        statement = self._dialect_insert(vocabulary_domains).values(
            domain_id=domain_id,
            name=name,
            description=description,
            discarded_at=None,
        )
        statement = statement.on_conflict_do_update(
            index_elements=[vocabulary_domains.c.domain_id],
            set_={
                "name": statement.excluded.name,
                "description": statement.excluded.description,
                "discarded_at": statement.excluded.discarded_at,
            },
        )
        await self._write([statement], tracking)

    async def change_domain(
        self,
        domain_id: UUID,
        name: str | None,
        description: str | None,
        tracking: Tracking,
    ) -> None:
        """Changes a domain, updating only the non-``None`` attributes."""
        values: dict[str, Any] = {}
        if name is not None:
            values["name"] = name
        if description is not None:
            values["description"] = description
        statements: list[Any] = []
        if values:
            statements.append(
                update(vocabulary_domains)
                .where(vocabulary_domains.c.domain_id == domain_id)
                .values(**values)
            )
        await self._write(statements, tracking)

    async def discard_domain(self, domain_id: UUID, tracking: Tracking) -> None:
        """Marks a domain, its terms and their children as discarded."""
        discarded_at = utc_now()
        term_ids = select(vocabulary_terms.c.term_id).where(
            vocabulary_terms.c.domain_id == domain_id
        )
        statements = [
            delete(vocabulary_term_aliases).where(vocabulary_term_aliases.c.term_id.in_(term_ids)),
            delete(vocabulary_term_links).where(vocabulary_term_links.c.term_id.in_(term_ids)),
            update(vocabulary_terms)
            .where(
                vocabulary_terms.c.domain_id == domain_id,
                vocabulary_terms.c.discarded_at.is_(None),
            )
            .values(discarded_at=discarded_at),
            update(vocabulary_domains)
            .where(vocabulary_domains.c.domain_id == domain_id)
            .values(discarded_at=discarded_at),
        ]
        await self._write(statements, tracking)

    async def get_domain(self, domain_id: UUID) -> DomainRow | None:
        """Returns the domain with the given ID, or ``None``."""
        row = await self._fetch_one(
            select(vocabulary_domains).where(
                vocabulary_domains.c.domain_id == domain_id,
                vocabulary_domains.c.discarded_at.is_(None),
            )
        )
        return None if row is None else self._domain_row(row)

    async def list_domains(self) -> list[DomainRow]:
        """Returns all live domains, ordered by name."""
        rows = await self._fetch_all(
            select(vocabulary_domains)
            .where(vocabulary_domains.c.discarded_at.is_(None))
            .order_by(vocabulary_domains.c.name)
        )
        return [self._domain_row(row) for row in rows]

    # -- term ---------------------------------------------------------------

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
        statement = self._dialect_insert(vocabulary_terms).values(
            term_id=term_id,
            domain_id=domain_id,
            parent_id=parent_id,
            path=path,
            name=name,
            definition=definition,
            status="draft",
            color=color,
            discarded_at=None,
        )
        statement = statement.on_conflict_do_update(
            index_elements=[vocabulary_terms.c.term_id],
            set_={
                "domain_id": statement.excluded.domain_id,
                "parent_id": statement.excluded.parent_id,
                "path": statement.excluded.path,
                "name": statement.excluded.name,
                "definition": statement.excluded.definition,
                "status": statement.excluded.status,
                "color": statement.excluded.color,
                "discarded_at": statement.excluded.discarded_at,
            },
        )
        statements: list[Any] = [
            delete(vocabulary_term_aliases).where(vocabulary_term_aliases.c.term_id == term_id),
            statement,
        ]
        statements.extend(
            self._dialect_insert(vocabulary_term_aliases)
            .values(term_id=term_id, alias=alias)
            .on_conflict_do_nothing()
            for alias in aliases
        )
        await self._write(statements, tracking)

    async def rename_term(
        self,
        term_id: UUID,
        new_name: str,
        new_path: str,
        tracking: Tracking,
    ) -> None:
        """Renames a term in the view."""
        statement = (
            update(vocabulary_terms)
            .where(vocabulary_terms.c.term_id == term_id)
            .values(name=new_name, path=new_path)
        )
        await self._write([statement], tracking)

    async def move_term(
        self,
        term_id: UUID,
        parent_id: UUID | None,
        new_path: str,
        tracking: Tracking,
    ) -> None:
        """Moves a term in the view."""
        statement = (
            update(vocabulary_terms)
            .where(vocabulary_terms.c.term_id == term_id)
            .values(parent_id=parent_id, path=new_path)
        )
        await self._write([statement], tracking)

    async def repath_term(self, term_id: UUID, new_path: str, tracking: Tracking) -> None:
        """Changes only the path of a term in the view."""
        statement = (
            update(vocabulary_terms)
            .where(vocabulary_terms.c.term_id == term_id)
            .values(path=new_path)
        )
        await self._write([statement], tracking)

    async def change_term_definition(
        self,
        term_id: UUID,
        definition: str,
        tracking: Tracking,
    ) -> None:
        """Replaces the definition of a term in the view."""
        statement = (
            update(vocabulary_terms)
            .where(vocabulary_terms.c.term_id == term_id)
            .values(definition=definition)
        )
        await self._write([statement], tracking)

    async def add_term_alias(self, term_id: UUID, alias: str, tracking: Tracking) -> None:
        """Adds an alias to a term in the view."""
        statement = (
            self._dialect_insert(vocabulary_term_aliases)
            .values(term_id=term_id, alias=alias)
            .on_conflict_do_nothing()
        )
        await self._write([statement], tracking)

    async def remove_term_alias(self, term_id: UUID, alias: str, tracking: Tracking) -> None:
        """Removes an alias from a term in the view."""
        statement = delete(vocabulary_term_aliases).where(
            vocabulary_term_aliases.c.term_id == term_id,
            vocabulary_term_aliases.c.alias == alias,
        )
        await self._write([statement], tracking)

    async def set_term_status(self, term_id: UUID, status: str, tracking: Tracking) -> None:
        """Sets the lifecycle status of a term in the view."""
        statement = (
            update(vocabulary_terms)
            .where(vocabulary_terms.c.term_id == term_id)
            .values(status=status)
        )
        await self._write([statement], tracking)

    async def set_term_color(self, term_id: UUID, color: str, tracking: Tracking) -> None:
        """Sets the presentation colour of a term in the view."""
        statement = (
            update(vocabulary_terms)
            .where(vocabulary_terms.c.term_id == term_id)
            .values(color=color)
        )
        await self._write([statement], tracking)

    async def discard_term(self, term_id: UUID, tracking: Tracking) -> None:
        """Marks one term as discarded and drops its aliases and links."""
        statements = [
            delete(vocabulary_term_aliases).where(vocabulary_term_aliases.c.term_id == term_id),
            delete(vocabulary_term_links).where(vocabulary_term_links.c.term_id == term_id),
            update(vocabulary_terms)
            .where(
                vocabulary_terms.c.term_id == term_id,
                vocabulary_terms.c.discarded_at.is_(None),
            )
            .values(discarded_at=utc_now()),
        ]
        await self._write(statements, tracking)

    async def get_term(self, term_id: UUID) -> TermRow | None:
        """Returns the term with the given ID, or ``None``."""
        row = await self._fetch_one(
            select(vocabulary_terms).where(
                vocabulary_terms.c.term_id == term_id,
                vocabulary_terms.c.discarded_at.is_(None),
            )
        )
        return None if row is None else self._term_row(row)

    async def list_terms(
        self,
        domain_id: UUID,
        status: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[TermRow]:
        """Returns the live terms of a domain, ordered by path."""
        statement = (
            select(vocabulary_terms)
            .where(
                vocabulary_terms.c.domain_id == domain_id,
                vocabulary_terms.c.discarded_at.is_(None),
            )
            .order_by(vocabulary_terms.c.path)
        )
        if status is not None:
            statement = statement.where(vocabulary_terms.c.status == status)
        if limit is not None:
            statement = statement.limit(limit)
        if offset:
            statement = statement.offset(offset)
        rows = await self._fetch_all(statement)
        return [self._term_row(row) for row in rows]

    async def list_children(self, domain_id: UUID, parent_id: UUID | None) -> list[TermRow]:
        """Returns the direct children of a term, or the top-level terms."""
        parent_condition = (
            vocabulary_terms.c.parent_id.is_(None)
            if parent_id is None
            else vocabulary_terms.c.parent_id == parent_id
        )
        rows = await self._fetch_all(
            select(vocabulary_terms)
            .where(
                vocabulary_terms.c.domain_id == domain_id,
                parent_condition,
                vocabulary_terms.c.discarded_at.is_(None),
            )
            .order_by(vocabulary_terms.c.path)
        )
        return [self._term_row(row) for row in rows]

    async def list_descendants(self, domain_id: UUID, term_id: UUID) -> list[TermRow]:
        """Returns every live descendant of a term, ordered by path."""
        row = await self._fetch_one(
            select(vocabulary_terms.c.path).where(
                vocabulary_terms.c.term_id == term_id,
                vocabulary_terms.c.discarded_at.is_(None),
            )
        )
        if row is None:
            return []
        prefix = f"{_escape_like(str(row.path))}/"
        rows = await self._fetch_all(
            select(vocabulary_terms)
            .where(
                vocabulary_terms.c.domain_id == domain_id,
                vocabulary_terms.c.path.like(f"{prefix}%", escape="\\"),
                vocabulary_terms.c.discarded_at.is_(None),
            )
            .order_by(vocabulary_terms.c.path)
        )
        return [self._term_row(row) for row in rows]

    async def find_term_id(self, domain_id: UUID, path: str) -> UUID | None:
        """Returns the term ID registered under a path, or ``None``."""
        row = await self._fetch_one(
            select(vocabulary_terms.c.term_id).where(
                vocabulary_terms.c.domain_id == domain_id,
                vocabulary_terms.c.path == path,
                vocabulary_terms.c.discarded_at.is_(None),
            )
        )
        return None if row is None else as_uuid(row.term_id)

    async def list_aliases(self, term_id: UUID) -> list[str]:
        """Returns the aliases of a term, ordered by name."""
        rows = await self._fetch_all(
            select(vocabulary_term_aliases.c.alias)
            .where(vocabulary_term_aliases.c.term_id == term_id)
            .order_by(vocabulary_term_aliases.c.alias)
        )
        return [str(row.alias) for row in rows]

    # -- links --------------------------------------------------------------

    async def link_term(
        self,
        term_id: UUID,
        target_id: UUID,
        target_kind: str,
        field_name: str,
        tracking: Tracking,
    ) -> None:
        """Records a catalog link of a term in the view."""
        statement = (
            self._dialect_insert(vocabulary_term_links)
            .values(
                term_id=term_id,
                target_id=target_id,
                target_kind=target_kind,
                field_name=field_name,
            )
            .on_conflict_do_nothing()
        )
        await self._write([statement], tracking)

    async def unlink_term(
        self,
        term_id: UUID,
        target_id: UUID,
        target_kind: str,
        field_name: str,
        tracking: Tracking,
    ) -> None:
        """Removes a catalog link of a term in the view."""
        statement = delete(vocabulary_term_links).where(
            vocabulary_term_links.c.term_id == term_id,
            vocabulary_term_links.c.target_id == target_id,
            vocabulary_term_links.c.target_kind == target_kind,
            vocabulary_term_links.c.field_name == field_name,
        )
        await self._write([statement], tracking)

    async def list_links(self, term_id: UUID) -> list[TermLinkRow]:
        """Returns the catalog links of a term."""
        rows = await self._fetch_all(
            select(vocabulary_term_links)
            .where(vocabulary_term_links.c.term_id == term_id)
            .order_by(
                vocabulary_term_links.c.target_kind,
                vocabulary_term_links.c.target_id,
                vocabulary_term_links.c.field_name,
            )
        )
        return [self._link_row(row) for row in rows]

    # -- reverse lookups and search ----------------------------------------

    async def terms_for_target(
        self,
        target_id: UUID,
        target_kind: str,
        field_name: str = "",
    ) -> list[TermRow]:
        """Returns the live terms linked to exactly the given target."""
        rows = await self._fetch_all(
            select(vocabulary_terms)
            .join(
                vocabulary_term_links,
                vocabulary_term_links.c.term_id == vocabulary_terms.c.term_id,
            )
            .where(
                vocabulary_terms.c.discarded_at.is_(None),
                vocabulary_term_links.c.target_id == target_id,
                vocabulary_term_links.c.target_kind == target_kind,
                vocabulary_term_links.c.field_name == field_name,
            )
            .order_by(vocabulary_terms.c.path)
        )
        return [self._term_row(row) for row in rows]

    async def terms_for_table(self, table_id: UUID) -> list[TermRow]:
        """Returns the terms linked to a table or to any of its fields."""
        rows = await self._fetch_all(
            select(vocabulary_terms)
            .join(
                vocabulary_term_links,
                vocabulary_term_links.c.term_id == vocabulary_terms.c.term_id,
            )
            .where(
                vocabulary_terms.c.discarded_at.is_(None),
                vocabulary_term_links.c.target_id == table_id,
                or_(
                    vocabulary_term_links.c.target_kind == "table",
                    and_(
                        vocabulary_term_links.c.target_kind == "field",
                        vocabulary_term_links.c.field_name != "",
                    ),
                ),
            )
            .distinct()
            .order_by(vocabulary_terms.c.path)
        )
        return [self._term_row(row) for row in rows]

    async def search_terms(
        self,
        query: str,
        domain_id: UUID | None = None,
        status: str | None = None,
        limit: int | None = None,
    ) -> list[TermSearchResult]:
        """Finds terms whose name, definition or alias contains ``query``."""
        pattern = f"%{_escape_like(query)}%"
        alias_match = (
            select(
                vocabulary_term_aliases.c.term_id.label("term_id"),
                func.min(vocabulary_term_aliases.c.alias).label("matched_alias"),
            )
            .where(vocabulary_term_aliases.c.alias.like(pattern, escape="\\"))
            .group_by(vocabulary_term_aliases.c.term_id)
            .subquery()
        )
        statement = (
            select(
                vocabulary_domains.c.domain_id,
                vocabulary_domains.c.name.label("domain_name"),
                vocabulary_terms.c.term_id,
                vocabulary_terms.c.path.label("term_path"),
                vocabulary_terms.c.name.label("term_name"),
                vocabulary_terms.c.definition,
                vocabulary_terms.c.status,
                vocabulary_terms.c.color,
                alias_match.c.matched_alias,
            )
            .select_from(
                vocabulary_terms.join(
                    vocabulary_domains,
                    vocabulary_domains.c.domain_id == vocabulary_terms.c.domain_id,
                )
            )
            .outerjoin(alias_match, alias_match.c.term_id == vocabulary_terms.c.term_id)
            .where(
                vocabulary_terms.c.discarded_at.is_(None),
                vocabulary_domains.c.discarded_at.is_(None),
                or_(
                    vocabulary_terms.c.name.like(pattern, escape="\\"),
                    vocabulary_terms.c.definition.like(pattern, escape="\\"),
                    alias_match.c.matched_alias.is_not(None),
                ),
            )
            .order_by(vocabulary_terms.c.path)
        )
        if domain_id is not None:
            statement = statement.where(vocabulary_domains.c.domain_id == domain_id)
        if status is not None:
            statement = statement.where(vocabulary_terms.c.status == status)
        if limit is not None:
            statement = statement.limit(limit)
        rows = await self._fetch_all(statement)
        return [self._search_row(row) for row in rows]

    # -- row builders -------------------------------------------------------

    @staticmethod
    def _domain_row(row: Any) -> DomainRow:
        """Builds a domain row from a database row."""
        return DomainRow(
            domain_id=as_uuid(row.domain_id),
            name=str(row.name),
            description=str(row.description),
        )

    @staticmethod
    def _term_row(row: Any) -> TermRow:
        """Builds a term row from a database row."""
        parent_id = row.parent_id
        return TermRow(
            term_id=as_uuid(row.term_id),
            domain_id=as_uuid(row.domain_id),
            parent_id=None if parent_id is None else as_uuid(parent_id),
            path=str(row.path),
            name=str(row.name),
            definition=str(row.definition),
            status=str(row.status),
            color=str(row.color or ""),
        )

    @staticmethod
    def _link_row(row: Any) -> TermLinkRow:
        """Builds a link row from a database row."""
        return TermLinkRow(
            target_id=as_uuid(row.target_id),
            target_kind=str(row.target_kind),
            field_name=str(row.field_name),
        )

    @staticmethod
    def _search_row(row: Any) -> TermSearchResult:
        """Builds a search result from a database row."""
        matched_alias = row.matched_alias
        return TermSearchResult(
            domain_id=as_uuid(row.domain_id),
            domain_name=str(row.domain_name),
            term_id=as_uuid(row.term_id),
            term_path=str(row.term_path),
            term_name=str(row.term_name),
            definition=str(row.definition),
            status=str(row.status),
            matched_alias=None if matched_alias is None else str(matched_alias),
            color=str(row.color or ""),
        )
