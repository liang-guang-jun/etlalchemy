"""Asynchronous SQLAlchemy implementation of the IAM read model.

SQLAlchemy Core builds the table definitions and the DML statements; they are
executed on the async engine of the eventsourcing datastore, so a view change and
its tracking record share one transaction. The same class serves SQLite
(``aiosqlite``) and PostgreSQL (``psycopg``); only the upsert dialect differs.

Each projected event calls exactly one write method: the method receives the
event's :class:`Tracking` and performs the whole cascade of that event, because a
single-row tracking table accepts one tracking insert per transaction.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from eventsourcing.asyncio.sqlalchemy import (
    AsyncSQLAlchemyDatastore,
    AsyncSQLAlchemyTrackingRecorder,
)
from sqlalchemy import (
    Select,
    Table,
    and_,
    delete,
    func,
    or_,
    select,
    update,
)
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from etlalchemy.iam.projection.tables import (
    iam_api_keys,
    iam_audit_log,
    iam_auth_providers,
    iam_casbin_rules,
    iam_group_members,
    iam_groups,
    iam_identities,
    iam_oidc_creds,
    iam_password_creds,
    iam_permission_grants,
    iam_sessions,
    iam_tenant_members,
    iam_tenants,
    iam_users,
    metadata,
)
from etlalchemy.iam.projection.view import (
    ApiKeyRow,
    AuditEntry,
    AuditRow,
    CasbinRuleRow,
    GroupMemberRow,
    GroupRow,
    IamView,
    IdentityRow,
    MemberRow,
    PermissionGrantRow,
    ProviderRow,
    SessionRow,
    TenantRow,
    UserRow,
)

if TYPE_CHECKING:  # pragma: no cover
    from collections.abc import Sequence

    from eventsourcing.persistence import Tracking


def _now() -> datetime:
    """Returns the current UTC timestamp."""
    return datetime.now(UTC)


def _or_equals(column: Any, values: Sequence[Any]) -> Any:
    """Returns an ``IN`` predicate built from equality disjunctions."""
    return or_(*(column == value for value in values))


class SQLAlchemyIamView(AsyncSQLAlchemyTrackingRecorder, IamView):
    """Asynchronous materialised view of the IAM aggregates."""

    def __init__(
        self,
        datastore: AsyncSQLAlchemyDatastore,
        *,
        tracking_table: Table,
    ) -> None:
        """Builds the view and resets its Casbin policy generation counter."""
        super().__init__(datastore, tracking_table=tracking_table)
        self._policy_generation = 0

    async def create_table(self) -> None:
        """Creates the tracking table and the view tables if they do not exist."""
        async with self.datastore.transaction() as conn:
            await conn.run_sync(metadata.create_all)
            await conn.run_sync(self.datastore.metadata.create_all)

    def _insert(self, table: Table) -> Any:
        """Returns the upsert construct of the configured dialect."""
        if self.datastore.dialect_name == AsyncSQLAlchemyDatastore.SQLITE:
            return sqlite_insert(table)
        return pg_insert(table)

    async def _write(
        self,
        statements: Sequence[Any],
        tracking: Tracking,
        audit: AuditEntry | None = None,
    ) -> None:
        """Applies the statements, the audit row and the tracking row atomically."""
        if audit is not None:
            statements = [*statements, self._audit_statement(audit)]
        async with self.transaction() as conn:
            for statement in statements:
                await conn.execute(statement)
            await self.insert_tracking_in_transaction(conn, tracking)

    def _audit_statement(self, entry: AuditEntry) -> Any:
        """Returns the insert of one audit record."""
        return iam_audit_log.insert().values(
            occurred_at=entry.occurred_at,
            actor_user_id=entry.actor_user_id,
            actor_identity_id=entry.actor_identity_id,
            action=entry.action,
            target_type=entry.target_type,
            target_id=entry.target_id,
            tenant_id=entry.tenant_id,
            result=entry.result,
            detail=entry.detail,
        )

    async def _fetch_all(self, statement: Select[Any]) -> Sequence[Any]:
        """Executes a read statement and returns all rows."""
        async with self.datastore.connection() as conn:
            rows: Sequence[Any] = (await conn.execute(statement)).all()
            return rows

    async def _fetch_one(self, statement: Select[Any]) -> Any:
        """Executes a read statement and returns the first row, or ``None``."""
        async with self.datastore.connection() as conn:
            return (await conn.execute(statement)).first()

    async def _fetch_scalar(self, statement: Select[Any]) -> int:
        """Executes a scalar read statement and returns an integer."""
        async with self.datastore.connection() as conn:
            value = await conn.scalar(statement)
        return int(value or 0)

    def policy_generation(self) -> int:
        """Returns a counter that changes whenever a Casbin rule is written."""
        return self._policy_generation

    # -- tenants ------------------------------------------------------------

    async def register_tenant(
        self,
        tenant_id: UUID,
        name: str,
        description: str,
        status: str,
        tracking: Tracking,
        audit: AuditEntry | None = None,
    ) -> None:
        """Registers a tenant, clearing a previous discarded marker."""
        statement = self._insert(iam_tenants).values(
            tenant_id=tenant_id,
            name=name,
            description=description,
            status=status,
            discarded_at=None,
        )
        statement = statement.on_conflict_do_update(
            index_elements=[iam_tenants.c.tenant_id],
            set_={
                "name": statement.excluded.name,
                "description": statement.excluded.description,
                "status": statement.excluded.status,
                "discarded_at": None,
            },
        )
        await self._write([statement], tracking, audit)

    async def change_tenant(
        self,
        tenant_id: UUID,
        name: str | None,
        description: str | None,
        status: str | None,
        tracking: Tracking,
        audit: AuditEntry | None = None,
    ) -> None:
        """Changes a tenant, updating only the non-``None`` attributes."""
        values: dict[str, Any] = {}
        if name is not None:
            values["name"] = name
        if description is not None:
            values["description"] = description
        if status is not None:
            values["status"] = status
        await self._write(
            [update(iam_tenants).where(iam_tenants.c.tenant_id == tenant_id).values(**values)],
            tracking,
            audit,
        )

    async def discard_tenant(
        self,
        tenant_id: UUID,
        tracking: Tracking,
        audit: AuditEntry | None = None,
    ) -> None:
        """Discards a tenant and cascades to its members, groups and rules."""
        now = _now()
        group_ids = [
            row[0]
            for row in await self._fetch_all(
                select(iam_groups.c.group_id).where(iam_groups.c.tenant_id == tenant_id),
            )
        ]
        statements: list[Any] = [
            update(iam_tenants)
            .where(iam_tenants.c.tenant_id == tenant_id)
            .values(discarded_at=now),
            delete(iam_tenant_members).where(iam_tenant_members.c.tenant_id == tenant_id),
        ]
        statements.extend(self._group_discard_statements(group_ids, now))
        statements.extend(self._casbin_tenant_delete_statements(tenant_id, group_ids))
        statements.append(self._revoke_tenant_sessions_statement(tenant_id, "tenant_discarded"))
        await self._write(statements, tracking, audit)

    async def get_tenant(self, tenant_id: UUID) -> TenantRow | None:
        """Returns one live tenant, or ``None``."""
        row = await self._fetch_one(
            select(
                iam_tenants.c.tenant_id,
                iam_tenants.c.name,
                iam_tenants.c.description,
                iam_tenants.c.status,
            ).where(
                iam_tenants.c.tenant_id == tenant_id,
                iam_tenants.c.discarded_at.is_(None),
            ),
        )
        return None if row is None else _tenant_row(row)

    async def find_tenant_by_name(self, name: str) -> TenantRow | None:
        """Returns the live tenant with the given name, or ``None``."""
        row = await self._fetch_one(
            select(
                iam_tenants.c.tenant_id,
                iam_tenants.c.name,
                iam_tenants.c.description,
                iam_tenants.c.status,
            ).where(
                func.lower(iam_tenants.c.name) == name.lower(),
                iam_tenants.c.discarded_at.is_(None),
            ),
        )
        return None if row is None else _tenant_row(row)

    async def list_tenants(self) -> list[TenantRow]:
        """Returns every live tenant, ordered by name."""
        rows = await self._fetch_all(
            select(
                iam_tenants.c.tenant_id,
                iam_tenants.c.name,
                iam_tenants.c.description,
                iam_tenants.c.status,
            )
            .where(iam_tenants.c.discarded_at.is_(None))
            .order_by(iam_tenants.c.name),
        )
        return [_tenant_row(row) for row in rows]

    # -- tenant members -----------------------------------------------------

    async def register_member(
        self,
        tenant_id: UUID,
        user_id: UUID,
        joined_at: datetime,
        status: str,
        tracking: Tracking,
    ) -> None:
        """Registers a tenant membership."""
        statement = self._insert(iam_tenant_members).values(
            tenant_id=tenant_id,
            user_id=user_id,
            joined_at=joined_at,
            status=status,
        )
        statement = statement.on_conflict_do_update(
            index_elements=[iam_tenant_members.c.tenant_id, iam_tenant_members.c.user_id],
            set_={
                "joined_at": statement.excluded.joined_at,
                "status": statement.excluded.status,
            },
        )
        await self._write([statement], tracking)

    async def remove_member(self, tenant_id: UUID, user_id: UUID, tracking: Tracking) -> None:
        """Removes a membership, its ``g`` rules and the sessions of that tenant."""
        key, tenant_key = str(user_id), str(tenant_id)
        await self._write(
            [
                delete(iam_tenant_members).where(
                    iam_tenant_members.c.tenant_id == tenant_id,
                    iam_tenant_members.c.user_id == user_id,
                ),
                delete(iam_casbin_rules).where(
                    iam_casbin_rules.c.ptype == "g",
                    iam_casbin_rules.c.v0 == key,
                    iam_casbin_rules.c.v2 == tenant_key,
                ),
                update(iam_sessions)
                .where(
                    iam_sessions.c.user_id == user_id,
                    iam_sessions.c.tenant_id == tenant_id,
                    iam_sessions.c.status == "ACTIVE",
                )
                .values(status="REVOKED", revoked_reason="membership_removed"),
            ],
            tracking,
        )
        self._policy_generation += 1

    async def change_member_status(
        self,
        tenant_id: UUID,
        user_id: UUID,
        status: str,
        tracking: Tracking,
    ) -> None:
        """Changes the status of one tenant membership."""
        await self._write(
            [
                update(iam_tenant_members)
                .where(
                    iam_tenant_members.c.tenant_id == tenant_id,
                    iam_tenant_members.c.user_id == user_id,
                )
                .values(status=status),
            ],
            tracking,
        )

    async def get_membership(self, tenant_id: UUID, user_id: UUID) -> MemberRow | None:
        """Returns one membership joined with its user, or ``None``."""
        row = await self._fetch_one(
            select(
                iam_tenant_members.c.tenant_id,
                iam_tenant_members.c.user_id,
                iam_users.c.username,
                iam_users.c.email,
                iam_tenant_members.c.joined_at,
                iam_tenant_members.c.status,
            )
            .select_from(
                iam_tenant_members.join(
                    iam_users,
                    iam_users.c.user_id == iam_tenant_members.c.user_id,
                ),
            )
            .where(
                iam_tenant_members.c.tenant_id == tenant_id,
                iam_tenant_members.c.user_id == user_id,
            ),
        )
        return None if row is None else _member_row(row)

    async def list_members(self, tenant_id: UUID) -> list[MemberRow]:
        """Returns the members of a tenant, ordered by username."""
        rows = await self._fetch_all(
            select(
                iam_tenant_members.c.tenant_id,
                iam_tenant_members.c.user_id,
                iam_users.c.username,
                iam_users.c.email,
                iam_tenant_members.c.joined_at,
                iam_tenant_members.c.status,
            )
            .select_from(
                iam_tenant_members.join(
                    iam_users,
                    iam_users.c.user_id == iam_tenant_members.c.user_id,
                ),
            )
            .where(
                iam_tenant_members.c.tenant_id == tenant_id,
                iam_users.c.discarded_at.is_(None),
            )
            .order_by(iam_users.c.username),
        )
        return [_member_row(row) for row in rows]

    async def list_memberships(self, user_id: UUID) -> list[MemberRow]:
        """Returns the live memberships of a user."""
        rows = await self._fetch_all(
            select(
                iam_tenant_members.c.tenant_id,
                iam_tenant_members.c.user_id,
                iam_users.c.username,
                iam_users.c.email,
                iam_tenant_members.c.joined_at,
                iam_tenant_members.c.status,
            )
            .select_from(
                iam_tenant_members.join(
                    iam_users,
                    iam_users.c.user_id == iam_tenant_members.c.user_id,
                ).join(
                    iam_tenants,
                    iam_tenants.c.tenant_id == iam_tenant_members.c.tenant_id,
                ),
            )
            .where(
                iam_tenant_members.c.user_id == user_id,
                iam_users.c.discarded_at.is_(None),
                iam_tenants.c.discarded_at.is_(None),
            )
            .order_by(iam_tenants.c.name),
        )
        return [_member_row(row) for row in rows]

    async def register_user(
        self,
        user_id: UUID,
        username: str,
        email: str,
        display_name: str,
        status: str,
        tracking: Tracking,
    ) -> None:
        """Registers a user, clearing a previous discarded marker."""
        statement = self._insert(iam_users).values(
            user_id=user_id,
            username=username,
            email=email,
            display_name=display_name,
            status=status,
            is_system_admin=False,
            discarded_at=None,
        )
        statement = statement.on_conflict_do_update(
            index_elements=[iam_users.c.user_id],
            set_={
                "username": statement.excluded.username,
                "email": statement.excluded.email,
                "display_name": statement.excluded.display_name,
                "status": statement.excluded.status,
                "discarded_at": None,
            },
        )
        await self._write([statement], tracking)

    async def change_user(
        self,
        user_id: UUID,
        username: str | None,
        email: str | None,
        display_name: str | None,
        status: str | None,
        tracking: Tracking,
    ) -> None:
        """Changes a user; a ``SUSPENDED`` status revokes every session."""
        values: dict[str, Any] = {}
        if username is not None:
            values["username"] = username
        if email is not None:
            values["email"] = email
        if display_name is not None:
            values["display_name"] = display_name
        if status is not None:
            values["status"] = status
        statements: list[Any] = [
            update(iam_users).where(iam_users.c.user_id == user_id).values(**values),
        ]
        if status == "SUSPENDED":
            statements.append(self._revoke_user_sessions_statement(user_id, "user_suspended"))
        await self._write(statements, tracking)

    async def set_system_admin(
        self,
        user_id: UUID,
        is_system_admin: bool,
        tracking: Tracking,
        audit: AuditEntry | None = None,
    ) -> None:
        """Sets the system administrator flag of a user."""
        await self._write(
            [
                update(iam_users)
                .where(iam_users.c.user_id == user_id)
                .values(is_system_admin=is_system_admin),
            ],
            tracking,
            audit,
        )

    async def discard_user(self, user_id: UUID, tracking: Tracking) -> None:
        """Discards a user and cascades to identities, sessions and rules."""
        now = _now()
        statements: list[Any] = [
            update(iam_users).where(iam_users.c.user_id == user_id).values(discarded_at=now),
            update(iam_identities)
            .where(iam_identities.c.user_id == user_id)
            .values(discarded_at=now),
            update(iam_api_keys)
            .where(iam_api_keys.c.user_id == user_id)
            .values(status="REVOKED", revoked_at=now),
            delete(iam_tenant_members).where(iam_tenant_members.c.user_id == user_id),
            delete(iam_casbin_rules).where(iam_casbin_rules.c.v0 == str(user_id)),
            self._revoke_user_sessions_statement(user_id, "user_discarded"),
        ]
        await self._write(statements, tracking)

    async def search_users(self, term: str, limit: int = 8) -> list[UserRow]:
        """Returns the live users whose name, username or email contains ``term``.

        A blank term is not an empty answer: it returns the first ``limit`` users,
        so typing a bare ``@`` already offers someone to mention.
        """
        needle = term.strip().lower()
        statement = select(
            iam_users.c.user_id,
            iam_users.c.username,
            iam_users.c.email,
            iam_users.c.display_name,
            iam_users.c.status,
            iam_users.c.is_system_admin,
        ).where(iam_users.c.discarded_at.is_(None))
        if needle != "":
            pattern = f"%{needle}%"
            statement = statement.where(
                or_(
                    func.lower(iam_users.c.username).like(pattern),
                    func.lower(iam_users.c.email).like(pattern),
                    func.lower(iam_users.c.display_name).like(pattern),
                )
            )
        rows = await self._fetch_all(
            statement.order_by(iam_users.c.display_name, iam_users.c.username).limit(limit)
        )
        return [_user_row(row) for row in rows]

    async def get_user(self, user_id: UUID) -> UserRow | None:
        """Returns one live user, or ``None``."""
        row = await self._fetch_one(
            select(
                iam_users.c.user_id,
                iam_users.c.username,
                iam_users.c.email,
                iam_users.c.display_name,
                iam_users.c.status,
                iam_users.c.is_system_admin,
            ).where(
                iam_users.c.user_id == user_id,
                iam_users.c.discarded_at.is_(None),
            ),
        )
        return None if row is None else _user_row(row)

    async def find_user_by_login(self, login: str) -> UserRow | None:
        """Returns the live user whose username or email matches ``login``."""
        lowered = login.lower()
        row = await self._fetch_one(
            select(
                iam_users.c.user_id,
                iam_users.c.username,
                iam_users.c.email,
                iam_users.c.display_name,
                iam_users.c.status,
                iam_users.c.is_system_admin,
            ).where(
                or_(
                    func.lower(iam_users.c.username) == lowered,
                    func.lower(iam_users.c.email) == lowered,
                ),
                iam_users.c.discarded_at.is_(None),
            ),
        )
        return None if row is None else _user_row(row)

    async def list_users(self) -> list[UserRow]:
        """Returns every live user, ordered by username."""
        rows = await self._fetch_all(
            select(
                iam_users.c.user_id,
                iam_users.c.username,
                iam_users.c.email,
                iam_users.c.display_name,
                iam_users.c.status,
                iam_users.c.is_system_admin,
            )
            .where(iam_users.c.discarded_at.is_(None))
            .order_by(iam_users.c.username),
        )
        return [_user_row(row) for row in rows]

    async def count_system_admins(self) -> int:
        """Returns the number of live system administrators."""
        return await self._fetch_scalar(
            select(func.count())
            .select_from(iam_users)
            .where(
                iam_users.c.is_system_admin.is_(True),
                iam_users.c.discarded_at.is_(None),
            ),
        )

    async def list_system_admins(self) -> list[UserRow]:
        """Returns the live system administrators, ordered by username."""
        rows = await self._fetch_all(
            select(
                iam_users.c.user_id,
                iam_users.c.username,
                iam_users.c.email,
                iam_users.c.display_name,
                iam_users.c.status,
                iam_users.c.is_system_admin,
            )
            .where(
                iam_users.c.is_system_admin.is_(True),
                iam_users.c.discarded_at.is_(None),
            )
            .order_by(iam_users.c.username),
        )
        return [_user_row(row) for row in rows]

    # -- identities ---------------------------------------------------------

    async def register_identity(
        self,
        identity_id: UUID,
        user_id: UUID,
        identity_type: str,
        provider: str,
        display_name: str,
        status: str,
        tracking: Tracking,
    ) -> None:
        """Registers an identity, clearing a previous discarded marker."""
        statement = self._insert(iam_identities).values(
            identity_id=identity_id,
            user_id=user_id,
            identity_type=identity_type,
            provider=provider,
            display_name=display_name,
            status=status,
            credential_version=0,
            provider_id=None,
            oidc_issuer=None,
            oidc_subject=None,
            last_used_at=None,
            discarded_at=None,
        )
        statement = statement.on_conflict_do_update(
            index_elements=[iam_identities.c.identity_id],
            set_={
                "identity_type": statement.excluded.identity_type,
                "provider": statement.excluded.provider,
                "display_name": statement.excluded.display_name,
                "status": statement.excluded.status,
                "discarded_at": None,
            },
        )
        await self._write([statement], tracking)

    async def change_identity(
        self,
        identity_id: UUID,
        display_name: str | None,
        status: str | None,
        tracking: Tracking,
    ) -> None:
        """Changes an identity; ``DISABLED`` revokes the sessions it issued."""
        values: dict[str, Any] = {}
        if display_name is not None:
            values["display_name"] = display_name
        if status is not None:
            values["status"] = status
        statements: list[Any] = [
            update(iam_identities)
            .where(iam_identities.c.identity_id == identity_id)
            .values(**values),
        ]
        if status == "DISABLED":
            statements.append(
                self._revoke_identity_sessions_statement(identity_id, "identity_disabled"),
            )
        await self._write(statements, tracking)

    async def set_password(
        self,
        identity_id: UUID,
        password_hash: str,
        credential_version: int,
        updated_at: datetime,
        tracking: Tracking,
        audit: AuditEntry | None = None,
    ) -> None:
        """Stores the password hash and revokes older sessions."""
        statement = self._insert(iam_password_creds).values(
            identity_id=identity_id,
            password_hash=password_hash,
            updated_at=updated_at,
        )
        statement = statement.on_conflict_do_update(
            index_elements=[iam_password_creds.c.identity_id],
            set_={
                "password_hash": statement.excluded.password_hash,
                "updated_at": statement.excluded.updated_at,
            },
        )
        await self._write(
            [
                update(iam_identities)
                .where(iam_identities.c.identity_id == identity_id)
                .values(credential_version=credential_version),
                statement,
                self._revoke_stale_sessions_statement(
                    identity_id,
                    credential_version,
                    "credential_changed",
                ),
            ],
            tracking,
            audit,
        )

    async def set_oidc_subject(
        self,
        identity_id: UUID,
        provider_id: UUID,
        issuer: str,
        subject: str,
        credential_version: int,
        tracking: Tracking,
        audit: AuditEntry | None = None,
    ) -> None:
        """Stores the OIDC binding and revokes older sessions."""
        statement = self._insert(iam_oidc_creds).values(
            identity_id=identity_id,
            provider_id=provider_id,
            issuer=issuer,
            subject=subject,
        )
        statement = statement.on_conflict_do_update(
            index_elements=[iam_oidc_creds.c.identity_id],
            set_={
                "provider_id": statement.excluded.provider_id,
                "issuer": statement.excluded.issuer,
                "subject": statement.excluded.subject,
            },
        )
        await self._write(
            [
                update(iam_identities)
                .where(iam_identities.c.identity_id == identity_id)
                .values(
                    provider_id=provider_id,
                    oidc_issuer=issuer,
                    oidc_subject=subject,
                    credential_version=credential_version,
                ),
                statement,
                self._revoke_stale_sessions_statement(
                    identity_id,
                    credential_version,
                    "credential_changed",
                ),
            ],
            tracking,
            audit,
        )

    async def discard_identity(
        self,
        identity_id: UUID,
        tracking: Tracking,
        audit: AuditEntry | None = None,
    ) -> None:
        """Discards an identity, its credentials, its keys and its sessions."""
        now = _now()
        statements: list[Any] = [
            update(iam_identities)
            .where(iam_identities.c.identity_id == identity_id)
            .values(discarded_at=now),
            delete(iam_password_creds).where(iam_password_creds.c.identity_id == identity_id),
            delete(iam_oidc_creds).where(iam_oidc_creds.c.identity_id == identity_id),
            update(iam_api_keys)
            .where(iam_api_keys.c.identity_id == identity_id)
            .values(status="REVOKED", revoked_at=now),
            self._revoke_identity_sessions_statement(identity_id, "identity_disabled"),
        ]
        await self._write(statements, tracking, audit)

    async def get_identity(self, identity_id: UUID) -> IdentityRow | None:
        """Returns one live identity, or ``None``."""
        row = await self._fetch_one(
            _identity_select().where(
                iam_identities.c.identity_id == identity_id,
                iam_identities.c.discarded_at.is_(None),
            ),
        )
        return None if row is None else _identity_row(row)

    async def list_identities(self, user_id: UUID) -> list[IdentityRow]:
        """Returns the live identities of a user."""
        rows = await self._fetch_all(
            _identity_select()
            .where(
                iam_identities.c.user_id == user_id,
                iam_identities.c.discarded_at.is_(None),
            )
            .order_by(iam_identities.c.identity_type),
        )
        return [_identity_row(row) for row in rows]

    async def find_password_identity(self, login: str) -> IdentityRow | None:
        """Returns the password identity of the user matching ``login``."""
        lowered = login.lower()
        row = await self._fetch_one(
            _identity_select()
            .select_from(
                iam_identities.join(
                    iam_users,
                    iam_users.c.user_id == iam_identities.c.user_id,
                ),
            )
            .where(
                or_(
                    func.lower(iam_users.c.username) == lowered,
                    func.lower(iam_users.c.email) == lowered,
                ),
                iam_identities.c.identity_type == "PASSWORD",
                iam_identities.c.status == "ACTIVE",
                iam_identities.c.discarded_at.is_(None),
                iam_users.c.discarded_at.is_(None),
            ),
        )
        return None if row is None else _identity_row(row)

    async def find_oidc_identity(self, issuer: str, subject: str) -> IdentityRow | None:
        """Returns the OIDC identity bound to an issuer and subject."""
        row = await self._fetch_one(
            _identity_select().where(
                iam_identities.c.oidc_issuer == issuer,
                iam_identities.c.oidc_subject == subject,
                iam_identities.c.discarded_at.is_(None),
            ),
        )
        return None if row is None else _identity_row(row)

    async def get_password_hash(self, identity_id: UUID) -> str | None:
        """Returns the password hash of an identity, or ``None``."""
        row = await self._fetch_one(
            select(iam_password_creds.c.password_hash).where(
                iam_password_creds.c.identity_id == identity_id,
            ),
        )
        return None if row is None else str(row[0])

    async def count_provider_identities(self, provider_id: UUID) -> int:
        """Returns the number of live identities bound to a provider."""
        return await self._fetch_scalar(
            select(func.count())
            .select_from(iam_identities)
            .where(
                iam_identities.c.provider_id == provider_id,
                iam_identities.c.discarded_at.is_(None),
            ),
        )

    # -- API keys -----------------------------------------------------------

    async def register_api_key(
        self,
        key_id: UUID,
        identity_id: UUID,
        user_id: UUID,
        prefix: str,
        secret_hash: str,
        scopes: list[str],
        created_at: datetime,
        expires_at: datetime | None,
        rotated_from: UUID | None,
        tracking: Tracking,
        audit: AuditEntry | None = None,
    ) -> None:
        """Registers an API key."""
        statement = self._insert(iam_api_keys).values(
            key_id=key_id,
            identity_id=identity_id,
            user_id=user_id,
            prefix=prefix,
            secret_hash=secret_hash,
            scopes=scopes,
            status="ACTIVE",
            created_at=created_at,
            expires_at=expires_at,
            grace_until=None,
            revoked_at=None,
            rotated_from=rotated_from,
            last_used_at=None,
        )
        statement = statement.on_conflict_do_update(
            index_elements=[iam_api_keys.c.key_id],
            set_={
                "prefix": statement.excluded.prefix,
                "secret_hash": statement.excluded.secret_hash,
                "scopes": statement.excluded.scopes,
                "status": "ACTIVE",
                "expires_at": statement.excluded.expires_at,
                "rotated_from": statement.excluded.rotated_from,
                "grace_until": None,
                "revoked_at": None,
            },
        )
        await self._write([statement], tracking, audit)

    async def rotate_api_key(
        self,
        old_key_id: UUID,
        new_key_id: UUID,
        identity_id: UUID,
        user_id: UUID,
        prefix: str,
        secret_hash: str,
        scopes: list[str],
        created_at: datetime,
        expires_at: datetime | None,
        grace_until: datetime,
        tracking: Tracking,
        audit: AuditEntry | None = None,
    ) -> None:
        """Moves the old key to ``GRACE``, inserts the new key, revokes old sessions."""
        statement = self._insert(iam_api_keys).values(
            key_id=new_key_id,
            identity_id=identity_id,
            user_id=user_id,
            prefix=prefix,
            secret_hash=secret_hash,
            scopes=scopes,
            status="ACTIVE",
            created_at=created_at,
            expires_at=expires_at,
            grace_until=None,
            revoked_at=None,
            rotated_from=old_key_id,
            last_used_at=None,
        )
        statement = statement.on_conflict_do_update(
            index_elements=[iam_api_keys.c.key_id],
            set_={
                "prefix": statement.excluded.prefix,
                "secret_hash": statement.excluded.secret_hash,
                "scopes": statement.excluded.scopes,
                "status": "ACTIVE",
                "expires_at": statement.excluded.expires_at,
                "rotated_from": statement.excluded.rotated_from,
            },
        )
        await self._write(
            [
                update(iam_api_keys)
                .where(iam_api_keys.c.key_id == old_key_id)
                .values(status="GRACE", grace_until=grace_until),
                statement,
                update(iam_sessions)
                .where(
                    iam_sessions.c.api_key_id == old_key_id,
                    iam_sessions.c.status == "ACTIVE",
                )
                .values(status="REVOKED", revoked_reason="api_key_rotated"),
            ],
            tracking,
            audit,
        )

    async def revoke_api_key(
        self,
        key_id: UUID,
        revoked_at: datetime,
        tracking: Tracking,
        audit: AuditEntry | None = None,
    ) -> None:
        """Revokes an API key and the sessions it issued."""
        await self._write(
            [
                update(iam_api_keys)
                .where(iam_api_keys.c.key_id == key_id)
                .values(status="REVOKED", revoked_at=revoked_at),
                update(iam_sessions)
                .where(
                    iam_sessions.c.api_key_id == key_id,
                    iam_sessions.c.status == "ACTIVE",
                )
                .values(status="REVOKED", revoked_reason="api_key_revoked"),
            ],
            tracking,
            audit,
        )

    async def list_api_keys(self, user_id: UUID) -> list[ApiKeyRow]:
        """Returns the API keys of a user, newest first."""
        rows = await self._fetch_all(
            select(
                iam_api_keys.c.key_id,
                iam_api_keys.c.identity_id,
                iam_api_keys.c.user_id,
                iam_api_keys.c.prefix,
                iam_api_keys.c.secret_hash,
                iam_api_keys.c.scopes,
                iam_api_keys.c.status,
                iam_api_keys.c.created_at,
                iam_api_keys.c.expires_at,
                iam_api_keys.c.grace_until,
                iam_api_keys.c.revoked_at,
                iam_api_keys.c.rotated_from,
                iam_api_keys.c.last_used_at,
            )
            .where(iam_api_keys.c.user_id == user_id)
            .order_by(iam_api_keys.c.created_at.desc()),
        )
        return [_api_key_row(row) for row in rows]

    async def get_api_key(self, key_id: UUID) -> ApiKeyRow | None:
        """Returns one API key, or ``None``."""
        row = await self._fetch_one(
            select(
                iam_api_keys.c.key_id,
                iam_api_keys.c.identity_id,
                iam_api_keys.c.user_id,
                iam_api_keys.c.prefix,
                iam_api_keys.c.secret_hash,
                iam_api_keys.c.scopes,
                iam_api_keys.c.status,
                iam_api_keys.c.created_at,
                iam_api_keys.c.expires_at,
                iam_api_keys.c.grace_until,
                iam_api_keys.c.revoked_at,
                iam_api_keys.c.rotated_from,
                iam_api_keys.c.last_used_at,
            ).where(iam_api_keys.c.key_id == key_id),
        )
        return None if row is None else _api_key_row(row)

    async def find_api_keys_by_prefix(self, prefix: str) -> list[ApiKeyRow]:
        """Returns the API keys that start with the given prefix."""
        rows = await self._fetch_all(
            select(
                iam_api_keys.c.key_id,
                iam_api_keys.c.identity_id,
                iam_api_keys.c.user_id,
                iam_api_keys.c.prefix,
                iam_api_keys.c.secret_hash,
                iam_api_keys.c.scopes,
                iam_api_keys.c.status,
                iam_api_keys.c.created_at,
                iam_api_keys.c.expires_at,
                iam_api_keys.c.grace_until,
                iam_api_keys.c.revoked_at,
                iam_api_keys.c.rotated_from,
                iam_api_keys.c.last_used_at,
            ).where(iam_api_keys.c.prefix == prefix),
        )
        return [_api_key_row(row) for row in rows]

    # -- sessions -----------------------------------------------------------

    async def register_session(
        self,
        session_id: UUID,
        identity_id: UUID,
        user_id: UUID,
        tenant_id: UUID | None,
        identity_type: str,
        api_key_id: UUID | None,
        credential_version: int,
        created_at: datetime,
        expires_at: datetime,
        tracking: Tracking,
    ) -> None:
        """Registers a session."""
        statement = self._insert(iam_sessions).values(
            session_id=session_id,
            identity_id=identity_id,
            user_id=user_id,
            tenant_id=tenant_id,
            identity_type=identity_type,
            api_key_id=api_key_id,
            credential_version=credential_version,
            status="ACTIVE",
            created_at=created_at,
            expires_at=expires_at,
            last_seen_at=created_at,
            revoked_reason=None,
        )
        statement = statement.on_conflict_do_update(
            index_elements=[iam_sessions.c.session_id],
            set_={
                "expires_at": statement.excluded.expires_at,
                "last_seen_at": statement.excluded.last_seen_at,
                "credential_version": statement.excluded.credential_version,
            },
        )
        await self._write([statement], tracking)

    async def refresh_session(
        self,
        session_id: UUID,
        expires_at: datetime,
        last_seen_at: datetime,
        tracking: Tracking,
    ) -> None:
        """Updates the expiry and the last use of a session."""
        await self._write(
            [
                update(iam_sessions)
                .where(iam_sessions.c.session_id == session_id)
                .values(expires_at=expires_at, last_seen_at=last_seen_at),
            ],
            tracking,
        )

    async def revoke_session(
        self,
        session_id: UUID,
        reason: str,
        tracking: Tracking,
        audit: AuditEntry | None = None,
    ) -> None:
        """Marks one session as revoked."""
        await self._write(
            [
                update(iam_sessions)
                .where(iam_sessions.c.session_id == session_id)
                .values(status="REVOKED", revoked_reason=reason),
            ],
            tracking,
            audit,
        )

    async def revoke_sessions_for_identity(
        self,
        identity_id: UUID,
        reason: str,
        tracking: Tracking,
    ) -> None:
        """Revokes every active session of an identity."""
        await self._write(
            [self._revoke_identity_sessions_statement(identity_id, reason)],
            tracking,
        )

    async def revoke_sessions_before_credential_version(
        self,
        identity_id: UUID,
        credential_version: int,
        reason: str,
        tracking: Tracking,
    ) -> None:
        """Revokes the sessions of an identity below a credential version."""
        await self._write(
            [self._revoke_stale_sessions_statement(identity_id, credential_version, reason)],
            tracking,
        )

    async def revoke_sessions_for_api_key(
        self,
        api_key_id: UUID,
        reason: str,
        tracking: Tracking,
    ) -> None:
        """Revokes every active session issued by an API key."""
        await self._write(
            [
                update(iam_sessions)
                .where(
                    iam_sessions.c.api_key_id == api_key_id,
                    iam_sessions.c.status == "ACTIVE",
                )
                .values(status="REVOKED", revoked_reason=reason),
            ],
            tracking,
        )

    async def revoke_sessions_for_user(
        self,
        user_id: UUID,
        reason: str,
        tracking: Tracking,
    ) -> None:
        """Revokes every active session of a user."""
        await self._write([self._revoke_user_sessions_statement(user_id, reason)], tracking)

    async def revoke_sessions_for_user_tenant(
        self,
        user_id: UUID,
        tenant_id: UUID,
        reason: str,
        tracking: Tracking,
    ) -> None:
        """Revokes the active sessions of a user in one tenant."""
        await self._write(
            [
                update(iam_sessions)
                .where(
                    iam_sessions.c.user_id == user_id,
                    iam_sessions.c.tenant_id == tenant_id,
                    iam_sessions.c.status == "ACTIVE",
                )
                .values(status="REVOKED", revoked_reason=reason),
            ],
            tracking,
        )

    async def revoke_sessions_for_tenant(
        self,
        tenant_id: UUID,
        reason: str,
        tracking: Tracking,
    ) -> None:
        """Revokes every active session that acts in a tenant."""
        await self._write([self._revoke_tenant_sessions_statement(tenant_id, reason)], tracking)

    async def get_session(self, session_id: UUID) -> SessionRow | None:
        """Returns one session, or ``None``."""
        row = await self._fetch_one(
            select(
                iam_sessions.c.session_id,
                iam_sessions.c.identity_id,
                iam_sessions.c.user_id,
                iam_sessions.c.tenant_id,
                iam_sessions.c.identity_type,
                iam_sessions.c.api_key_id,
                iam_sessions.c.credential_version,
                iam_sessions.c.status,
                iam_sessions.c.created_at,
                iam_sessions.c.expires_at,
                iam_sessions.c.last_seen_at,
                iam_sessions.c.revoked_reason,
            ).where(iam_sessions.c.session_id == session_id),
        )
        return None if row is None else _session_row(row)

    # -- groups -------------------------------------------------------------

    async def register_group(
        self,
        group_id: UUID,
        tenant_id: UUID,
        name: str,
        description: str,
        parent_group_id: UUID | None,
        tracking: Tracking,
    ) -> None:
        """Registers a group, clearing a previous discarded marker."""
        statement = self._insert(iam_groups).values(
            group_id=group_id,
            tenant_id=tenant_id,
            name=name,
            description=description,
            parent_group_id=parent_group_id,
            discarded_at=None,
        )
        statement = statement.on_conflict_do_update(
            index_elements=[iam_groups.c.group_id],
            set_={
                "name": statement.excluded.name,
                "description": statement.excluded.description,
                "parent_group_id": statement.excluded.parent_group_id,
                "discarded_at": None,
            },
        )
        await self._write([statement], tracking)

    async def change_group(
        self,
        group_id: UUID,
        name: str | None,
        description: str | None,
        tracking: Tracking,
    ) -> None:
        """Changes a group, updating only the non-``None`` attributes."""
        values: dict[str, Any] = {}
        if name is not None:
            values["name"] = name
        if description is not None:
            values["description"] = description
        await self._write(
            [update(iam_groups).where(iam_groups.c.group_id == group_id).values(**values)],
            tracking,
        )

    async def change_group_parent(
        self,
        group_id: UUID,
        parent_group_id: UUID | None,
        tracking: Tracking,
    ) -> None:
        """Updates the parent of a group and drops its own ``g`` edge."""
        await self._write(
            [
                update(iam_groups)
                .where(iam_groups.c.group_id == group_id)
                .values(parent_group_id=parent_group_id),
                delete(iam_casbin_rules).where(
                    iam_casbin_rules.c.ptype == "g",
                    iam_casbin_rules.c.v0 == str(group_id),
                ),
            ],
            tracking,
        )
        self._policy_generation += 1

    async def discard_groups(self, group_ids: list[UUID], tracking: Tracking) -> None:
        """Discards the given groups together with their members and rules."""
        now = _now()
        await self._write(self._group_discard_statements(group_ids, now), tracking)

    async def get_group(self, group_id: UUID) -> GroupRow | None:
        """Returns one live group, or ``None``."""
        row = await self._fetch_one(
            select(
                iam_groups.c.group_id,
                iam_groups.c.tenant_id,
                iam_groups.c.name,
                iam_groups.c.description,
                iam_groups.c.parent_group_id,
            ).where(
                iam_groups.c.group_id == group_id,
                iam_groups.c.discarded_at.is_(None),
            ),
        )
        return None if row is None else _group_row(row)

    async def find_group_by_name(
        self,
        tenant_id: UUID,
        parent_group_id: UUID | None,
        name: str,
    ) -> GroupRow | None:
        """Returns the live sibling group with the given name, or ``None``."""
        condition = (
            iam_groups.c.parent_group_id.is_(None)
            if parent_group_id is None
            else iam_groups.c.parent_group_id == parent_group_id
        )
        row = await self._fetch_one(
            select(
                iam_groups.c.group_id,
                iam_groups.c.tenant_id,
                iam_groups.c.name,
                iam_groups.c.description,
                iam_groups.c.parent_group_id,
            ).where(
                iam_groups.c.tenant_id == tenant_id,
                func.lower(iam_groups.c.name) == name.lower(),
                condition,
                iam_groups.c.discarded_at.is_(None),
            ),
        )
        return None if row is None else _group_row(row)

    async def list_groups(self, tenant_id: UUID) -> list[GroupRow]:
        """Returns the live groups of a tenant, ordered by name."""
        rows = await self._fetch_all(
            select(
                iam_groups.c.group_id,
                iam_groups.c.tenant_id,
                iam_groups.c.name,
                iam_groups.c.description,
                iam_groups.c.parent_group_id,
            )
            .where(
                iam_groups.c.tenant_id == tenant_id,
                iam_groups.c.discarded_at.is_(None),
            )
            .order_by(iam_groups.c.name),
        )
        return [_group_row(row) for row in rows]

    async def add_group_member(
        self,
        group_id: UUID,
        member_id: UUID,
        member_kind: str,
        tenant_id: UUID,
        added_at: datetime,
        tracking: Tracking,
    ) -> None:
        """Adds a member to a group and writes its ``g`` rule."""
        statement = self._insert(iam_group_members).values(
            group_id=group_id,
            member_id=member_id,
            member_kind=member_kind,
            added_at=added_at,
        )
        statement = statement.on_conflict_do_nothing(
            index_elements=[
                iam_group_members.c.group_id,
                iam_group_members.c.member_id,
                iam_group_members.c.member_kind,
            ],
        )
        rule = self._insert(iam_casbin_rules).values(
            ptype="g",
            v0=str(member_id),
            v1=str(group_id),
            v2=str(tenant_id),
            v3="",
        )
        rule = rule.on_conflict_do_nothing(
            index_elements=[
                iam_casbin_rules.c.ptype,
                iam_casbin_rules.c.v0,
                iam_casbin_rules.c.v1,
                iam_casbin_rules.c.v2,
                iam_casbin_rules.c.v3,
            ],
        )
        await self._write([statement, rule], tracking)
        self._policy_generation += 1

    async def remove_group_member(
        self,
        group_id: UUID,
        member_id: UUID,
        member_kind: str,
        tracking: Tracking,
    ) -> None:
        """Removes a member from a group and deletes its ``g`` rule."""
        await self._write(
            [
                delete(iam_group_members).where(
                    iam_group_members.c.group_id == group_id,
                    iam_group_members.c.member_id == member_id,
                    iam_group_members.c.member_kind == member_kind,
                ),
                delete(iam_casbin_rules).where(
                    iam_casbin_rules.c.ptype == "g",
                    iam_casbin_rules.c.v0 == str(member_id),
                    iam_casbin_rules.c.v1 == str(group_id),
                ),
            ],
            tracking,
        )
        self._policy_generation += 1

    async def list_group_members(self, tenant_id: UUID) -> list[GroupMemberRow]:
        """Returns every group membership of a tenant."""
        rows = await self._fetch_all(
            select(
                iam_group_members.c.group_id,
                iam_group_members.c.member_id,
                iam_group_members.c.member_kind,
                iam_group_members.c.added_at,
            )
            .select_from(
                iam_group_members.join(
                    iam_groups,
                    iam_groups.c.group_id == iam_group_members.c.group_id,
                ),
            )
            .where(iam_groups.c.tenant_id == tenant_id),
        )
        return [
            GroupMemberRow(
                group_id=row[0],
                member_id=row[1],
                member_kind=row[2],
                added_at=row[3],
            )
            for row in rows
        ]

    async def grant_permission(
        self,
        group_id: UUID,
        tenant_id: UUID,
        obj: str,
        act: str,
        tracking: Tracking,
    ) -> None:
        """Registers a permission grant and writes its ``p`` rule."""
        statement = self._insert(iam_permission_grants).values(
            group_id=group_id,
            tenant_id=tenant_id,
            object=obj,
            action=act,
        )
        statement = statement.on_conflict_do_nothing(
            index_elements=[
                iam_permission_grants.c.group_id,
                iam_permission_grants.c.tenant_id,
                iam_permission_grants.c.object,
                iam_permission_grants.c.action,
            ],
        )
        rule = self._insert(iam_casbin_rules).values(
            ptype="p",
            v0=str(group_id),
            v1=str(tenant_id),
            v2=obj,
            v3=act,
        )
        rule = rule.on_conflict_do_nothing(
            index_elements=[
                iam_casbin_rules.c.ptype,
                iam_casbin_rules.c.v0,
                iam_casbin_rules.c.v1,
                iam_casbin_rules.c.v2,
                iam_casbin_rules.c.v3,
            ],
        )
        await self._write([statement, rule], tracking)
        self._policy_generation += 1

    async def revoke_permission(
        self,
        group_id: UUID,
        tenant_id: UUID,
        obj: str,
        act: str,
        tracking: Tracking,
    ) -> None:
        """Removes a permission grant and deletes its ``p`` rule."""
        await self._write(
            [
                delete(iam_permission_grants).where(
                    iam_permission_grants.c.group_id == group_id,
                    iam_permission_grants.c.tenant_id == tenant_id,
                    iam_permission_grants.c.object == obj,
                    iam_permission_grants.c.action == act,
                ),
                delete(iam_casbin_rules).where(
                    iam_casbin_rules.c.ptype == "p",
                    iam_casbin_rules.c.v0 == str(group_id),
                    iam_casbin_rules.c.v1 == str(tenant_id),
                    iam_casbin_rules.c.v2 == obj,
                    iam_casbin_rules.c.v3 == act,
                ),
            ],
            tracking,
        )
        self._policy_generation += 1

    async def list_permission_grants(self, tenant_id: UUID) -> list[PermissionGrantRow]:
        """Returns the permission grants of a tenant."""
        rows = await self._fetch_all(
            select(
                iam_permission_grants.c.group_id,
                iam_permission_grants.c.tenant_id,
                iam_permission_grants.c.object,
                iam_permission_grants.c.action,
            ).where(iam_permission_grants.c.tenant_id == tenant_id),
        )
        return [
            PermissionGrantRow(
                group_id=row[0],
                tenant_id=row[1],
                obj=row[2],
                act=row[3],
            )
            for row in rows
        ]

    # -- auth providers -----------------------------------------------------

    async def register_provider(
        self,
        provider_id: UUID,
        provider_key: str,
        kind: str,
        display_name: str,
        tenant_id: UUID | None,
        config: dict[str, str],
        status: str,
        tracking: Tracking,
        audit: AuditEntry | None = None,
    ) -> None:
        """Registers an auth provider, clearing a previous discarded marker."""
        statement = self._insert(iam_auth_providers).values(
            provider_id=provider_id,
            provider_key=provider_key,
            kind=kind,
            display_name=display_name,
            tenant_id=tenant_id,
            config=config,
            status=status,
            discarded_at=None,
        )
        statement = statement.on_conflict_do_update(
            index_elements=[iam_auth_providers.c.provider_id],
            set_={
                "provider_key": statement.excluded.provider_key,
                "kind": statement.excluded.kind,
                "display_name": statement.excluded.display_name,
                "tenant_id": statement.excluded.tenant_id,
                "config": statement.excluded.config,
                "status": statement.excluded.status,
                "discarded_at": None,
            },
        )
        await self._write([statement], tracking, audit)

    async def change_provider(
        self,
        provider_id: UUID,
        display_name: str | None,
        status: str | None,
        tracking: Tracking,
        audit: AuditEntry | None = None,
    ) -> None:
        """Changes a provider, updating only the non-``None`` attributes."""
        values: dict[str, Any] = {}
        if display_name is not None:
            values["display_name"] = display_name
        if status is not None:
            values["status"] = status
        await self._write(
            [
                update(iam_auth_providers)
                .where(iam_auth_providers.c.provider_id == provider_id)
                .values(**values),
            ],
            tracking,
            audit,
        )

    async def update_provider_config(
        self,
        provider_id: UUID,
        config: dict[str, str],
        tracking: Tracking,
        audit: AuditEntry | None = None,
    ) -> None:
        """Replaces the configuration of a provider."""
        await self._write(
            [
                update(iam_auth_providers)
                .where(iam_auth_providers.c.provider_id == provider_id)
                .values(config=config),
            ],
            tracking,
            audit,
        )

    async def discard_provider(
        self,
        provider_id: UUID,
        tracking: Tracking,
        audit: AuditEntry | None = None,
    ) -> None:
        """Marks a provider as discarded."""
        await self._write(
            [
                update(iam_auth_providers)
                .where(iam_auth_providers.c.provider_id == provider_id)
                .values(discarded_at=_now()),
            ],
            tracking,
            audit,
        )

    async def get_provider(self, provider_id: UUID) -> ProviderRow | None:
        """Returns one live provider, or ``None``."""
        row = await self._fetch_one(
            select(
                iam_auth_providers.c.provider_id,
                iam_auth_providers.c.provider_key,
                iam_auth_providers.c.kind,
                iam_auth_providers.c.display_name,
                iam_auth_providers.c.tenant_id,
                iam_auth_providers.c.config,
                iam_auth_providers.c.status,
            ).where(
                iam_auth_providers.c.provider_id == provider_id,
                iam_auth_providers.c.discarded_at.is_(None),
            ),
        )
        return None if row is None else _provider_row(row)

    async def find_provider_by_key(self, provider_key: str) -> ProviderRow | None:
        """Returns the live provider with the given key, or ``None``."""
        row = await self._fetch_one(
            select(
                iam_auth_providers.c.provider_id,
                iam_auth_providers.c.provider_key,
                iam_auth_providers.c.kind,
                iam_auth_providers.c.display_name,
                iam_auth_providers.c.tenant_id,
                iam_auth_providers.c.config,
                iam_auth_providers.c.status,
            ).where(
                iam_auth_providers.c.provider_key == provider_key,
                iam_auth_providers.c.discarded_at.is_(None),
            ),
        )
        return None if row is None else _provider_row(row)

    async def list_providers(self) -> list[ProviderRow]:
        """Returns every live provider, ordered by key."""
        rows = await self._fetch_all(
            select(
                iam_auth_providers.c.provider_id,
                iam_auth_providers.c.provider_key,
                iam_auth_providers.c.kind,
                iam_auth_providers.c.display_name,
                iam_auth_providers.c.tenant_id,
                iam_auth_providers.c.config,
                iam_auth_providers.c.status,
            )
            .where(iam_auth_providers.c.discarded_at.is_(None))
            .order_by(iam_auth_providers.c.provider_key),
        )
        return [_provider_row(row) for row in rows]

    # -- casbin -------------------------------------------------------------

    async def add_casbin_rules(
        self,
        rules: list[CasbinRuleRow],
        tracking: Tracking,
    ) -> None:
        """Inserts Casbin rules, ignoring rules that already exist."""
        statements = [
            self._insert(iam_casbin_rules)
            .values(ptype=rule.ptype, v0=rule.v0, v1=rule.v1, v2=rule.v2, v3=rule.v3)
            .on_conflict_do_nothing(
                index_elements=[
                    iam_casbin_rules.c.ptype,
                    iam_casbin_rules.c.v0,
                    iam_casbin_rules.c.v1,
                    iam_casbin_rules.c.v2,
                    iam_casbin_rules.c.v3,
                ],
            )
            for rule in rules
        ]
        await self._write(statements, tracking)
        self._policy_generation += 1

    async def remove_casbin_rules(
        self,
        rules: list[CasbinRuleRow],
        tracking: Tracking,
    ) -> None:
        """Deletes the given Casbin rules."""
        condition = or_(
            *(
                and_(
                    iam_casbin_rules.c.ptype == rule.ptype,
                    iam_casbin_rules.c.v0 == rule.v0,
                    iam_casbin_rules.c.v1 == rule.v1,
                    iam_casbin_rules.c.v2 == rule.v2,
                    iam_casbin_rules.c.v3 == rule.v3,
                )
                for rule in rules
            ),
        )
        await self._write([delete(iam_casbin_rules).where(condition)], tracking)
        self._policy_generation += 1

    async def remove_casbin_rules_for_groups(
        self,
        group_ids: list[UUID],
        tracking: Tracking,
    ) -> None:
        """Deletes every ``p``/``g`` rule that mentions one of the groups."""
        await self._write(self._casbin_group_delete_statements(group_ids), tracking)
        self._policy_generation += 1

    async def remove_casbin_rules_for_subject(
        self,
        subject: UUID,
        tenant_id: UUID | None,
        tracking: Tracking,
    ) -> None:
        """Deletes the ``g`` rules of a user, optionally in one tenant."""
        condition = iam_casbin_rules.c.v0 == str(subject)
        if tenant_id is not None:
            condition = and_(condition, iam_casbin_rules.c.v2 == str(tenant_id))
        await self._write([delete(iam_casbin_rules).where(condition)], tracking)
        self._policy_generation += 1

    async def list_casbin_rules(self) -> list[CasbinRuleRow]:
        """Returns every Casbin rule."""
        rows = await self._fetch_all(
            select(
                iam_casbin_rules.c.ptype,
                iam_casbin_rules.c.v0,
                iam_casbin_rules.c.v1,
                iam_casbin_rules.c.v2,
                iam_casbin_rules.c.v3,
            ),
        )
        return [
            CasbinRuleRow(ptype=row[0], v0=row[1], v1=row[2], v2=row[3], v3=row[4]) for row in rows
        ]

    # -- audit --------------------------------------------------------------

    async def add_audit(
        self,
        entry: AuditEntry,
        tracking: Tracking,
    ) -> None:
        """Appends one standalone audit record."""
        await self._write([self._audit_statement(entry)], tracking)

    async def list_audit_events(
        self,
        limit: int = 50,
        offset: int = 0,
        action: str | None = None,
        actor_user_id: UUID | None = None,
    ) -> list[AuditRow]:
        """Returns audit records, newest first."""
        statement = select(
            iam_audit_log.c.audit_id,
            iam_audit_log.c.occurred_at,
            iam_audit_log.c.actor_user_id,
            iam_audit_log.c.actor_identity_id,
            iam_audit_log.c.action,
            iam_audit_log.c.target_type,
            iam_audit_log.c.target_id,
            iam_audit_log.c.tenant_id,
            iam_audit_log.c.result,
            iam_audit_log.c.detail,
        )
        if action is not None:
            statement = statement.where(iam_audit_log.c.action == action)
        if actor_user_id is not None:
            statement = statement.where(iam_audit_log.c.actor_user_id == actor_user_id)
        rows = await self._fetch_all(
            statement.order_by(iam_audit_log.c.audit_id.desc()).limit(limit).offset(offset),
        )
        return [_audit_row(row) for row in rows]

    # -- shared statements --------------------------------------------------

    def _revoke_identity_sessions_statement(self, identity_id: UUID, reason: str) -> Any:
        """Returns the statement that revokes the sessions of one identity."""
        return (
            update(iam_sessions)
            .where(
                iam_sessions.c.identity_id == identity_id,
                iam_sessions.c.status == "ACTIVE",
            )
            .values(status="REVOKED", revoked_reason=reason)
        )

    def _revoke_stale_sessions_statement(
        self,
        identity_id: UUID,
        credential_version: int,
        reason: str,
    ) -> Any:
        """Returns the statement that revokes sessions below a credential version."""
        return (
            update(iam_sessions)
            .where(
                iam_sessions.c.identity_id == identity_id,
                iam_sessions.c.credential_version < credential_version,
                iam_sessions.c.status == "ACTIVE",
            )
            .values(status="REVOKED", revoked_reason=reason)
        )

    def _revoke_user_sessions_statement(self, user_id: UUID, reason: str) -> Any:
        """Returns the statement that revokes every session of a user."""
        return (
            update(iam_sessions)
            .where(
                iam_sessions.c.user_id == user_id,
                iam_sessions.c.status == "ACTIVE",
            )
            .values(status="REVOKED", revoked_reason=reason)
        )

    def _revoke_tenant_sessions_statement(self, tenant_id: UUID, reason: str) -> Any:
        """Returns the statement that revokes every session of a tenant."""
        return (
            update(iam_sessions)
            .where(
                iam_sessions.c.tenant_id == tenant_id,
                iam_sessions.c.status == "ACTIVE",
            )
            .values(status="REVOKED", revoked_reason=reason)
        )

    def _group_discard_statements(self, group_ids: list[UUID], now: datetime) -> list[Any]:
        """Returns the statements that discard a set of groups and their rules."""
        if not group_ids:
            return []
        return [
            update(iam_groups)
            .where(_or_equals(iam_groups.c.group_id, group_ids))
            .values(discarded_at=now),
            delete(iam_group_members).where(
                _or_equals(iam_group_members.c.group_id, group_ids),
            ),
            delete(iam_permission_grants).where(
                _or_equals(iam_permission_grants.c.group_id, group_ids),
            ),
            *self._casbin_group_delete_statements(group_ids),
        ]

    def _casbin_group_delete_statements(self, group_ids: list[UUID]) -> list[Any]:
        """Returns the statements that delete the rules mentioning the groups."""
        if not group_ids:
            return []
        keys = [str(group_id) for group_id in group_ids]
        return [
            delete(iam_casbin_rules).where(
                or_(
                    and_(
                        iam_casbin_rules.c.ptype == "p",
                        _or_equals(iam_casbin_rules.c.v0, keys),
                    ),
                    and_(
                        iam_casbin_rules.c.ptype == "g",
                        or_(
                            _or_equals(iam_casbin_rules.c.v0, keys),
                            _or_equals(iam_casbin_rules.c.v1, keys),
                        ),
                    ),
                ),
            ),
        ]

    def _casbin_tenant_delete_statements(
        self,
        tenant_id: UUID,
        group_ids: list[UUID],
    ) -> list[Any]:
        """Returns the statements that delete the rules of a tenant."""
        key = str(tenant_id)
        statements = [
            delete(iam_casbin_rules).where(iam_casbin_rules.c.v1 == key),
            delete(iam_casbin_rules).where(iam_casbin_rules.c.v2 == key),
        ]
        statements.extend(self._casbin_group_delete_statements(group_ids))
        return statements


def _identity_select() -> Select[Any]:
    """Returns the shared identity projection."""
    return select(
        iam_identities.c.identity_id,
        iam_identities.c.user_id,
        iam_identities.c.identity_type,
        iam_identities.c.provider,
        iam_identities.c.display_name,
        iam_identities.c.status,
        iam_identities.c.credential_version,
        iam_identities.c.provider_id,
        iam_identities.c.oidc_issuer,
        iam_identities.c.oidc_subject,
        iam_identities.c.last_used_at,
    )


def _tenant_row(row: Any) -> TenantRow:
    """Maps a tenant record to its row dataclass."""
    return TenantRow(tenant_id=row[0], name=row[1], description=row[2], status=row[3])


def _member_row(row: Any) -> MemberRow:
    """Maps a membership record to its row dataclass."""
    return MemberRow(
        tenant_id=row[0],
        user_id=row[1],
        username=row[2],
        email=row[3],
        joined_at=row[4],
        status=row[5],
    )


def _user_row(row: Any) -> UserRow:
    """Maps a user record to its row dataclass."""
    return UserRow(
        user_id=row[0],
        username=row[1],
        email=row[2],
        display_name=row[3],
        status=row[4],
        is_system_admin=bool(row[5]),
    )


def _identity_row(row: Any) -> IdentityRow:
    """Maps an identity record to its row dataclass."""
    return IdentityRow(
        identity_id=row[0],
        user_id=row[1],
        identity_type=row[2],
        provider=row[3],
        display_name=row[4],
        status=row[5],
        credential_version=row[6],
        provider_id=row[7],
        oidc_issuer=row[8],
        oidc_subject=row[9],
        last_used_at=row[10],
    )


def _api_key_row(row: Any) -> ApiKeyRow:
    """Maps an API key record to its row dataclass."""
    return ApiKeyRow(
        key_id=row[0],
        identity_id=row[1],
        user_id=row[2],
        prefix=row[3],
        secret_hash=row[4],
        scopes=list(row[5] or []),
        status=row[6],
        created_at=row[7],
        expires_at=row[8],
        grace_until=row[9],
        revoked_at=row[10],
        rotated_from=row[11],
        last_used_at=row[12],
    )


def _session_row(row: Any) -> SessionRow:
    """Maps a session record to its row dataclass."""
    return SessionRow(
        session_id=row[0],
        identity_id=row[1],
        user_id=row[2],
        tenant_id=row[3],
        identity_type=row[4],
        api_key_id=row[5],
        credential_version=row[6],
        status=row[7],
        created_at=row[8],
        expires_at=row[9],
        last_seen_at=row[10],
        revoked_reason=row[11],
    )


def _group_row(row: Any) -> GroupRow:
    """Maps a group record to its row dataclass."""
    return GroupRow(
        group_id=row[0],
        tenant_id=row[1],
        name=row[2],
        description=row[3],
        parent_group_id=row[4],
    )


def _provider_row(row: Any) -> ProviderRow:
    """Maps a provider record to its row dataclass."""
    return ProviderRow(
        provider_id=row[0],
        provider_key=row[1],
        kind=row[2],
        display_name=row[3],
        tenant_id=row[4],
        config=dict(row[5] or {}),
        status=row[6],
    )


def _audit_row(row: Any) -> AuditRow:
    """Maps an audit record to its row dataclass."""
    return AuditRow(
        audit_id=row[0],
        occurred_at=row[1],
        actor_user_id=row[2],
        actor_identity_id=row[3],
        action=row[4],
        target_type=row[5],
        target_id=row[6],
        tenant_id=row[7],
        result=row[8],
        detail=dict(row[9] or {}),
    )


__all__ = ["SQLAlchemyIamView"]
