from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from functools import wraps
from typing import TYPE_CHECKING, Any, Literal, ParamSpec, TypeVar, cast

import sqlalchemy as sa
import sqlalchemy.exc as sa_exc
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine
from sqlalchemy.pool import StaticPool

from etlalchemy._vendor.eventsourcing.asyncio.persistence import (
    AsyncAggregateRecorder,
    AsyncApplicationRecorder,
    AsyncInfrastructureFactory,
    AsyncPollingSubscription,
    AsyncProcessRecorder,
    AsyncRecorder,
    AsyncTrackingRecorder,
)
from eventsourcing.persistence import (
    DatabaseError,
    DataError,
    InfrastructureFactoryError,
    IntegrityError,
    InterfaceError,
    InternalError,
    Notification,
    NotSupportedError,
    OperationalError,
    PersistenceError,
    ProgrammingError,
    StoredEvent,
    Tracking,
)
from eventsourcing.utils import Environment, EnvType, resolve_topic, strtobool

if TYPE_CHECKING:
    from collections.abc import (
        AsyncIterator,
        Callable,
        Coroutine,
        Sequence,
    )

_P = ParamSpec("_P")
_R = TypeVar("_R")


def translate_exceptions(
    func: Callable[_P, Coroutine[Any, Any, _R]],
) -> Callable[_P, Coroutine[Any, Any, _R]]:
    """Translates SQLAlchemy exceptions into this library's exception classes."""

    @wraps(func)
    async def wrapper(*args: _P.args, **kwargs: _P.kwargs) -> _R:
        try:
            return await func(*args, **kwargs)
        except sa_exc.InterfaceError as e:
            raise InterfaceError(str(e)) from e
        except sa_exc.DataError as e:
            raise DataError(str(e)) from e
        except sa_exc.OperationalError as e:
            raise OperationalError(str(e)) from e
        except sa_exc.IntegrityError as e:
            raise IntegrityError(str(e)) from e
        except sa_exc.InternalError as e:
            raise InternalError(str(e)) from e
        except sa_exc.ProgrammingError as e:
            raise ProgrammingError(str(e)) from e
        except sa_exc.NotSupportedError as e:
            raise NotSupportedError(str(e)) from e
        except sa_exc.DatabaseError as e:
            raise DatabaseError(str(e)) from e
        except sa_exc.SQLAlchemyError as e:
            raise PersistenceError(str(e)) from e

    return wrapper


class AsyncSQLAlchemyDatastore:
    """Asynchronous datastore implemented with SQLAlchemy's async engine.

    The database dialect is selected by the URL, for example
    'sqlite+aiosqlite:///:memory:' or
    'postgresql+psycopg://user:password@host:5432/dbname'.
    """

    SQLITE = "sqlite"
    POSTGRESQL = "postgresql"

    def __init__(
        self,
        url: str,
        *,
        pool_size: int = 5,
        max_overflow: int = 10,
        pool_timeout: float = 5.0,
        pool_recycle: float = 3600.0,
        echo: bool = False,
        originator_id_type: str = "uuid",
        single_row_tracking: bool = True,
    ) -> None:
        if originator_id_type.lower() not in ("uuid", "text"):
            msg = (
                f"Invalid originator_id_type '{originator_id_type}', "
                "must be 'uuid' or 'text'"
            )
            raise ValueError(msg)
        self.url = url
        self.originator_id_type = originator_id_type.lower()
        self.single_row_tracking = single_row_tracking

        try:
            url_obj = sa.engine.make_url(url)
        except sa_exc.ArgumentError as e:
            msg = f"Invalid SQLAlchemy database URL '{url}': {e}"
            raise InfrastructureFactoryError(msg) from e
        expected_dialect_name = url_obj.get_backend_name()
        if expected_dialect_name not in (self.SQLITE, self.POSTGRESQL):
            msg = (
                f"Unsupported database dialect '{expected_dialect_name}', "
                "expected 'sqlite' or 'postgresql'"
            )
            raise NotSupportedError(msg)

        engine_kwargs: dict[str, Any] = {"echo": echo}
        if self.is_memory_url(url):
            engine_kwargs["poolclass"] = StaticPool
        else:
            engine_kwargs.update(
                pool_size=pool_size,
                max_overflow=max_overflow,
                pool_timeout=pool_timeout,
                pool_recycle=pool_recycle,
            )

        try:
            self.engine: AsyncEngine = create_async_engine(url, **engine_kwargs)
        except (sa_exc.SQLAlchemyError, ModuleNotFoundError, ImportError) as e:
            msg = f"Failed to create async database engine for URL '{url}': {e}"
            raise InfrastructureFactoryError(msg) from e

        self.dialect_name: str = self.engine.dialect.name

        self.metadata = sa.MetaData()

        # In-memory SQLite uses a single shared connection (StaticPool).
        # Concurrent users of that connection would interfere with each
        # other's transactions, so serialize access.
        self._access_lock: asyncio.Lock | None = (
            asyncio.Lock() if self.is_memory_url(url) else None
        )

    @staticmethod
    def is_memory_url(url: str) -> bool:
        return ":memory:" in url or "mode=memory" in url

    def _originator_id_column_type(self) -> sa.types.TypeEngine[Any]:
        return sa.Uuid() if self.originator_id_type == "uuid" else sa.Text()

    def create_events_table(self, name: str) -> sa.Table:
        existing = self.metadata.tables.get(name)
        if existing is not None:
            return existing
        return sa.Table(
            name,
            self.metadata,
            sa.Column(
                "originator_id",
                self._originator_id_column_type(),
                nullable=False,
            ),
            sa.Column("originator_version", sa.BigInteger(), nullable=False),
            sa.Column("topic", sa.Text(), nullable=False),
            sa.Column("state", sa.LargeBinary(), nullable=False),
            sa.UniqueConstraint(
                "originator_id",
                "originator_version",
                name=f"{name}_originator_uc",
            ),
        )

    def create_application_events_table(self, name: str) -> sa.Table:
        existing = self.metadata.tables.get(name)
        if existing is not None:
            return existing
        # SQLite only makes an INTEGER primary key an alias for the rowid,
        # so use Integer for SQLite and BigInteger for PostgreSQL (bigserial).
        notification_id_type = (
            sa.Integer() if self.dialect_name == self.SQLITE else sa.BigInteger()
        )
        return sa.Table(
            name,
            self.metadata,
            sa.Column(
                "notification_id",
                notification_id_type,
                primary_key=True,
                autoincrement=True,
            ),
            sa.Column(
                "originator_id",
                self._originator_id_column_type(),
                nullable=False,
            ),
            sa.Column("originator_version", sa.BigInteger(), nullable=False),
            sa.Column("topic", sa.Text(), nullable=False),
            sa.Column("state", sa.LargeBinary(), nullable=False),
            sa.UniqueConstraint(
                "originator_id",
                "originator_version",
                name=f"{name}_originator_uc",
            ),
        )

    def create_tracking_table(self, name: str) -> sa.Table:
        existing = self.metadata.tables.get(name)
        if existing is not None:
            return existing
        if self.single_row_tracking:
            return sa.Table(
                name,
                self.metadata,
                sa.Column("application_name", sa.Text(), primary_key=True),
                sa.Column("notification_id", sa.BigInteger(), nullable=False),
            )
        return sa.Table(
            name,
            self.metadata,
            sa.Column("application_name", sa.Text(), primary_key=True),
            sa.Column("notification_id", sa.BigInteger(), primary_key=True),
        )

    async def create_tables(self) -> None:
        async with self.transaction() as conn:
            await conn.run_sync(self.metadata.create_all)

    @asynccontextmanager
    async def connection(self) -> AsyncIterator[AsyncConnection]:
        """Provides a connection for read operations."""
        if self._access_lock is not None:
            await self._access_lock.acquire()
        try:
            async with self.engine.connect() as conn:
                yield conn
        finally:
            if self._access_lock is not None:
                self._access_lock.release()

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[AsyncConnection]:
        """Provides a connection with a transaction."""
        if self._access_lock is not None:
            await self._access_lock.acquire()
        try:
            async with self.engine.begin() as conn:
                yield conn
        finally:
            if self._access_lock is not None:
                self._access_lock.release()

    async def close(self) -> None:
        await self.engine.dispose()

    def quoted_table_name(self, table: sa.Table) -> str:
        return self.engine.dialect.identifier_preparer.quote(table.name)


class AsyncSQLAlchemyRecorder(AsyncRecorder):
    def __init__(self, datastore: AsyncSQLAlchemyDatastore) -> None:
        self.datastore = datastore

    async def create_table(self) -> None:
        await self.datastore.create_tables()


class AsyncSQLAlchemyAggregateRecorder(AsyncSQLAlchemyRecorder, AsyncAggregateRecorder):
    def __init__(
        self,
        datastore: AsyncSQLAlchemyDatastore,
        *,
        events_table: sa.Table,
    ) -> None:
        super().__init__(datastore)
        self.events_table = events_table

    @staticmethod
    def _stored_event_values(stored_event: StoredEvent) -> dict[str, Any]:
        return {
            "originator_id": stored_event.originator_id,
            "originator_version": stored_event.originator_version,
            "topic": stored_event.topic,
            "state": stored_event.state,
        }

    @translate_exceptions
    async def insert_events(
        self, stored_events: Sequence[StoredEvent], **kwargs: Any
    ) -> Sequence[int] | None:
        if not stored_events:
            return None
        async with self.datastore.transaction() as conn:
            await self._insert_events(conn, stored_events)
        return None

    async def _insert_events(
        self,
        conn: AsyncConnection,
        stored_events: Sequence[StoredEvent],
        **kwargs: Any,
    ) -> None:
        await conn.execute(
            sa.insert(self.events_table),
            [self._stored_event_values(e) for e in stored_events],
        )

    @translate_exceptions
    async def select_events(
        self,
        originator_id: Any,
        *,
        gt: int | None = None,
        lte: int | None = None,
        desc: bool = False,
        limit: int | None = None,
    ) -> Sequence[StoredEvent]:
        t = self.events_table
        statement = sa.select(
            t.c.originator_id,
            t.c.originator_version,
            t.c.topic,
            t.c.state,
        ).where(t.c.originator_id == originator_id)
        if gt is not None:
            statement = statement.where(t.c.originator_version > gt)
        if lte is not None:
            statement = statement.where(t.c.originator_version <= lte)
        statement = statement.order_by(
            t.c.originator_version.desc() if desc else t.c.originator_version.asc()
        )
        if limit is not None:
            statement = statement.limit(limit)
        async with self.datastore.connection() as conn:
            rows = (await conn.execute(statement)).all()
        return [
            StoredEvent(
                originator_id=row.originator_id,
                originator_version=row.originator_version,
                topic=row.topic,
                state=bytes(row.state),
            )
            for row in rows
        ]


class AsyncSQLAlchemyApplicationRecorder(
    AsyncSQLAlchemyAggregateRecorder, AsyncApplicationRecorder
):
    @translate_exceptions
    async def insert_events(
        self, stored_events: Sequence[StoredEvent], **kwargs: Any
    ) -> Sequence[int] | None:
        if not stored_events:
            return []
        async with self.datastore.transaction() as conn:
            await self._lock_events_table(conn)
            return await self._insert_notification_events(conn, stored_events)

    async def _lock_events_table(self, conn: AsyncConnection) -> None:
        if self.datastore.dialect_name == AsyncSQLAlchemyDatastore.POSTGRESQL:
            # Serialize inserts so that notification IDs are issued and
            # committed in the same order, and readers don't pass over gaps.
            lock_statement = sa.text(
                "LOCK TABLE "
                f"{self.datastore.quoted_table_name(self.events_table)} "
                "IN EXCLUSIVE MODE"
            )
            await conn.execute(lock_statement)

    async def _insert_notification_events(
        self,
        conn: AsyncConnection,
        stored_events: Sequence[StoredEvent],
    ) -> Sequence[int]:
        if not stored_events:
            return []
        statement = sa.insert(self.events_table).returning(
            self.events_table.c.notification_id
        )
        result = await conn.execute(
            statement,
            [self._stored_event_values(e) for e in stored_events],
        )
        return [row[0] for row in result.all()]

    @translate_exceptions
    async def select_notifications(
        self,
        start: int | None,
        limit: int,
        stop: int | None = None,
        topics: Sequence[str] = (),
        *,
        inclusive_of_start: bool = True,
    ) -> Sequence[Notification]:
        t = self.events_table
        statement = sa.select(
            t.c.notification_id,
            t.c.originator_id,
            t.c.originator_version,
            t.c.topic,
            t.c.state,
        )
        if start is not None:
            if inclusive_of_start:
                statement = statement.where(t.c.notification_id >= start)
            else:
                statement = statement.where(t.c.notification_id > start)
        if stop is not None:
            statement = statement.where(t.c.notification_id <= stop)
        if topics:
            statement = statement.where(t.c.topic.in_(list(topics)))
        statement = statement.order_by(t.c.notification_id.asc()).limit(limit)
        async with self.datastore.connection() as conn:
            rows = (await conn.execute(statement)).all()
        return [
            Notification(
                id=row.notification_id,
                originator_id=row.originator_id,
                originator_version=row.originator_version,
                topic=row.topic,
                state=bytes(row.state),
            )
            for row in rows
        ]

    @translate_exceptions
    async def max_notification_id(self) -> int | None:
        t = self.events_table
        statement = sa.select(sa.func.max(t.c.notification_id))
        async with self.datastore.connection() as conn:
            return (await conn.execute(statement)).scalar_one()

    def subscribe(
        self, gt: int | None = None, topics: Sequence[str] = ()
    ) -> AsyncPollingSubscription[AsyncSQLAlchemyApplicationRecorder]:
        return AsyncPollingSubscription(self, gt=gt, topics=topics)


class AsyncSQLAlchemyTrackingRecorder(AsyncSQLAlchemyRecorder, AsyncTrackingRecorder):
    def __init__(
        self,
        datastore: AsyncSQLAlchemyDatastore,
        *,
        tracking_table: sa.Table,
    ) -> None:
        super().__init__(datastore)
        self.tracking_table = tracking_table

    @translate_exceptions
    async def insert_tracking(self, tracking: Tracking) -> None:
        async with self.datastore.transaction() as conn:
            await self.insert_tracking_in_transaction(conn, tracking)

    async def insert_tracking_in_transaction(
        self,
        conn: AsyncConnection,
        tracking: Tracking,
    ) -> None:
        """Inserts a tracking object using an existing connection/transaction.

        This method is intended for custom views that need to record a tracking
        object atomically with their own state.
        """
        t = self.tracking_table
        values = {
            "application_name": tracking.application_name,
            "notification_id": tracking.notification_id,
        }
        if self.datastore.single_row_tracking:
            insert_statement = self._dialect_insert(t).values(**values)
            statement = insert_statement.on_conflict_do_update(
                index_elements=[t.c.application_name],
                set_={
                    "notification_id": insert_statement.excluded.notification_id,
                },
                where=(t.c.notification_id < insert_statement.excluded.notification_id),
            ).returning(t.c.notification_id)
            result = await conn.execute(statement)
            if result.first() is None:
                msg = (
                    "Failed to record tracking for "
                    f"{tracking.application_name} {tracking.notification_id}"
                )
                raise IntegrityError(msg)
        else:
            await conn.execute(self._dialect_insert(t).values(**values))

    def _dialect_insert(self, table: sa.Table) -> Any:
        if self.datastore.dialect_name == AsyncSQLAlchemyDatastore.SQLITE:
            return sqlite.insert(table)
        return postgresql.insert(table)

    @translate_exceptions
    async def max_tracking_id(self, application_name: str) -> int | None:
        t = self.tracking_table
        statement = sa.select(sa.func.max(t.c.notification_id)).where(
            t.c.application_name == application_name
        )
        async with self.datastore.connection() as conn:
            return (await conn.execute(statement)).scalar_one()

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[AsyncConnection]:
        """Provides an async transaction for custom view operations."""
        async with self.datastore.transaction() as conn:
            yield conn


class AsyncSQLAlchemyProcessRecorder(
    AsyncSQLAlchemyTrackingRecorder,
    AsyncSQLAlchemyApplicationRecorder,
    AsyncProcessRecorder,
):
    def __init__(
        self,
        datastore: AsyncSQLAlchemyDatastore,
        *,
        events_table: sa.Table,
        tracking_table: sa.Table,
    ) -> None:
        AsyncSQLAlchemyApplicationRecorder.__init__(
            self, datastore, events_table=events_table
        )
        self.tracking_table = tracking_table

    @translate_exceptions
    async def insert_events(
        self, stored_events: Sequence[StoredEvent], **kwargs: Any
    ) -> Sequence[int] | None:
        tracking: Tracking | None = kwargs.get("tracking")
        if not stored_events and tracking is None:
            return []
        async with self.datastore.transaction() as conn:
            await self._lock_events_table(conn)
            notification_ids = await self._insert_notification_events(
                conn, stored_events
            )
            if tracking is not None:
                await self.insert_tracking_in_transaction(conn, tracking)
        return notification_ids


class AsyncSQLAlchemyFactory(
    AsyncInfrastructureFactory[AsyncSQLAlchemyTrackingRecorder]
):
    SQLALCHEMY_URL = "SQLALCHEMY_URL"
    SQLALCHEMY_POOL_SIZE = "SQLALCHEMY_POOL_SIZE"
    SQLALCHEMY_MAX_OVERFLOW = "SQLALCHEMY_MAX_OVERFLOW"
    SQLALCHEMY_POOL_TIMEOUT = "SQLALCHEMY_POOL_TIMEOUT"
    SQLALCHEMY_POOL_RECYCLE = "SQLALCHEMY_POOL_RECYCLE"
    SQLALCHEMY_ECHO = "SQLALCHEMY_ECHO"
    CREATE_TABLE = "CREATE_TABLE"
    SINGLE_ROW_TRACKING = "SINGLE_ROW_TRACKING"
    ORIGINATOR_ID_TYPE = "ORIGINATOR_ID_TYPE"

    aggregate_recorder_class = AsyncSQLAlchemyAggregateRecorder
    application_recorder_class = AsyncSQLAlchemyApplicationRecorder
    tracking_recorder_class = AsyncSQLAlchemyTrackingRecorder
    process_recorder_class = AsyncSQLAlchemyProcessRecorder

    def __init__(self, env: Environment | EnvType | None):
        super().__init__(env)
        url = self.env.get(self.SQLALCHEMY_URL)
        if not url:
            msg = (
                "SQLAlchemy database URL not found in environment with key "
                f"'{self.SQLALCHEMY_URL}'"
            )
            raise OSError(msg)

        originator_id_type = cast(
            Literal["uuid", "text"],
            self.env.get(self.ORIGINATOR_ID_TYPE, "uuid"),
        )
        if originator_id_type.lower() not in ("uuid", "text"):
            msg = (
                f"Invalid {self.ORIGINATOR_ID_TYPE} '{originator_id_type}', "
                "must be 'uuid' or 'text'"
            )
            raise OSError(msg)

        single_row_tracking = strtobool(self.env.get(self.SINGLE_ROW_TRACKING, "t"))
        if not single_row_tracking:
            msg = "Async recorders only support single-row tracking"
            raise NotSupportedError(msg)

        self.datastore = AsyncSQLAlchemyDatastore(
            url,
            pool_size=self._int_env(self.SQLALCHEMY_POOL_SIZE, 5),
            max_overflow=self._int_env(self.SQLALCHEMY_MAX_OVERFLOW, 10),
            pool_timeout=self._float_env(self.SQLALCHEMY_POOL_TIMEOUT, 5.0),
            pool_recycle=self._float_env(self.SQLALCHEMY_POOL_RECYCLE, 3600.0),
            echo=strtobool(self.env.get(self.SQLALCHEMY_ECHO, "no")),
            originator_id_type=originator_id_type,
            single_row_tracking=single_row_tracking,
        )
        self._recorders: list[AsyncSQLAlchemyRecorder] = []

    def _int_env(self, key: str, default: int) -> int:
        value = self.env.get(key)
        if value is None or not value.strip():
            return default
        try:
            return int(value)
        except ValueError:
            msg = (
                f"SQLAlchemy environment value for key '{key}' is invalid. "
                f"If set, an integer is expected: '{value}'"
            )
            raise OSError(msg) from None

    def _float_env(self, key: str, default: float) -> float:
        value = self.env.get(key)
        if value is None or not value.strip():
            return default
        try:
            return float(value)
        except ValueError:
            msg = (
                f"SQLAlchemy environment value for key '{key}' is invalid. "
                f"If set, a float is expected: '{value}'"
            )
            raise OSError(msg) from None

    def env_create_table(self) -> bool:
        return strtobool(self.env.get(self.CREATE_TABLE) or "yes")

    async def start(self) -> None:
        if self._is_started:
            return
        if self.env_create_table():
            for recorder in self._recorders:
                await recorder.create_table()
        self._is_started = True

    async def aclose(self) -> None:
        self._recorders.clear()
        await self.datastore.close()
        self._is_started = False

    def _stored_prefix(self) -> str:
        return self.env.name.lower() or "stored"

    def _tracking_prefix(self) -> str:
        return self.env.name.lower() or "notification"

    def aggregate_recorder(self, purpose: str = "events") -> AsyncAggregateRecorder:
        table = self.datastore.create_events_table(f"{self._stored_prefix()}_{purpose}")
        recorder = type(self).aggregate_recorder_class(
            datastore=self.datastore,
            events_table=table,
        )
        self._recorders.append(recorder)
        return recorder

    def application_recorder(self) -> AsyncApplicationRecorder:
        application_recorder_topic = self.env.get(self.APPLICATION_RECORDER_TOPIC)
        if application_recorder_topic:
            application_recorder_class: type[AsyncSQLAlchemyApplicationRecorder] = (
                resolve_topic(application_recorder_topic)
            )
            assert issubclass(
                application_recorder_class, AsyncSQLAlchemyApplicationRecorder
            )
        else:
            application_recorder_class = type(self).application_recorder_class

        table = self.datastore.create_application_events_table(
            f"{self._stored_prefix()}_events"
        )
        recorder = application_recorder_class(
            datastore=self.datastore,
            events_table=table,
        )
        self._recorders.append(recorder)
        return recorder

    def tracking_recorder(
        self,
        tracking_recorder_class: type[AsyncSQLAlchemyTrackingRecorder] | None = None,
    ) -> AsyncSQLAlchemyTrackingRecorder:
        if tracking_recorder_class is None:
            tracking_recorder_topic = self.env.get(self.TRACKING_RECORDER_TOPIC)
            if tracking_recorder_topic:
                tracking_recorder_class = resolve_topic(tracking_recorder_topic)
            else:
                tracking_recorder_class = type(self).tracking_recorder_class

        assert issubclass(
            tracking_recorder_class, AsyncSQLAlchemyTrackingRecorder
        ), tracking_recorder_class
        table = self.datastore.create_tracking_table(
            f"{self._tracking_prefix()}_tracking"
        )
        recorder = tracking_recorder_class(
            datastore=self.datastore,
            tracking_table=table,
        )
        self._recorders.append(recorder)
        return recorder

    def process_recorder(self) -> AsyncProcessRecorder:
        process_recorder_topic = self.env.get(self.PROCESS_RECORDER_TOPIC)
        if process_recorder_topic:
            process_recorder_class: type[AsyncSQLAlchemyProcessRecorder] = (
                resolve_topic(process_recorder_topic)
            )
            assert issubclass(process_recorder_class, AsyncSQLAlchemyProcessRecorder)
        else:
            process_recorder_class = type(self).process_recorder_class

        events_table = self.datastore.create_application_events_table(
            f"{self._stored_prefix()}_events"
        )
        tracking_table = self.datastore.create_tracking_table(
            f"{self._tracking_prefix()}_tracking"
        )
        recorder = process_recorder_class(
            datastore=self.datastore,
            events_table=events_table,
            tracking_table=tracking_table,
        )
        self._recorders.append(recorder)
        return recorder


Factory = AsyncSQLAlchemyFactory
