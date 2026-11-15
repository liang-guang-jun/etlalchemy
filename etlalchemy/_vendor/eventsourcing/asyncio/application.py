from __future__ import annotations

import asyncio
import contextlib
import os
from abc import ABC, abstractmethod
from copy import deepcopy
from itertools import chain
from typing import (
    TYPE_CHECKING,
    Any,
    ClassVar,
    Generic,
    cast,
)

from eventsourcing.application import (
    AggregateNotFoundError,
    Cache,
    LRUCache,
    ProcessingEvent,
    ProgrammingError,
    ProjectorFunction,
    Section,
    project_aggregate,
)
from etlalchemy._vendor.eventsourcing.asyncio.persistence import (
    AsyncApplicationRecorder,
    AsyncEventStore,
    AsyncInfrastructureFactory,
)
from eventsourcing.domain import (
    BaseAggregate,
    CanMutateProtocol,
    DomainEventProtocol,
    MutableOrImmutableAggregate,
    SnapshotProtocol,
    TAggregateID,
    TDomainEvent,
    TMutableOrImmutableAggregate,
)
from eventsourcing.persistence import (
    DatetimeAsISO,
    DecimalAsStr,
    JSONTranscoder,
    Mapper,
    Notification,
    Recording,
    Transcoder,
    UUIDAsHex,
)
from eventsourcing.utils import Environment, EnvType, strtobool

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence
    from types import TracebackType
    from typing import Self


class AsyncRepository(Generic[TAggregateID]):
    """Asynchronously reconstructs aggregates from events in an
    :class:`~etlalchemy._vendor.eventsourcing.asyncio.persistence.AsyncEventStore`.
    """

    FASTFORWARD_LOCKS_CACHE_MAXSIZE = 50

    def __init__(
        self,
        event_store: AsyncEventStore[TAggregateID],
        *,
        snapshot_store: AsyncEventStore[TAggregateID] | None = None,
        cache_maxsize: int | None = None,
        fastforward: bool = True,
        fastforward_skipping: bool = False,
        deepcopy_from_cache: bool = True,
    ):
        self.event_store = event_store
        self.snapshot_store = snapshot_store

        if cache_maxsize is None:
            self.cache: (
                Cache[TAggregateID, MutableOrImmutableAggregate[TAggregateID]] | None
            ) = None
        elif cache_maxsize <= 0:
            self.cache = Cache()
        else:
            self.cache = LRUCache(maxsize=cache_maxsize)
        self.fastforward = fastforward
        self.fastforward_skipping = fastforward_skipping
        self.deepcopy_from_cache = deepcopy_from_cache

        self._fastforward_locks_cache: LRUCache[TAggregateID, asyncio.Lock] = LRUCache(
            maxsize=self.FASTFORWARD_LOCKS_CACHE_MAXSIZE
        )
        self._fastforward_locks_inuse: dict[TAggregateID, tuple[asyncio.Lock, int]] = {}

    async def get(
        self,
        aggregate_id: TAggregateID,
        *,
        version: int | None = None,
        projector_func: ProjectorFunction[
            TMutableOrImmutableAggregate, TDomainEvent
        ] = project_aggregate,
        fastforward_skipping: bool = False,
        deepcopy_from_cache: bool = True,
    ) -> TMutableOrImmutableAggregate:
        """Reconstructs an aggregate for a given ID from stored events."""
        if self.cache and version is None:
            try:
                aggregate = cast(
                    "TMutableOrImmutableAggregate", self.cache.get(aggregate_id)
                )
            except KeyError:
                aggregate = await self._reconstruct_aggregate(
                    aggregate_id, None, projector_func
                )
                self.cache.put(aggregate_id, aggregate)
            else:
                if self.fastforward:
                    lock = self._use_fastforward_lock(aggregate_id)
                    blocking = not (fastforward_skipping or self.fastforward_skipping)
                    try:
                        acquired = False
                        if blocking or not lock.locked():
                            await lock.acquire()
                            acquired = True
                        if acquired:
                            try:
                                new_events = await self.event_store.get(
                                    originator_id=aggregate_id,
                                    gt=aggregate.version,
                                )
                                _aggregate = projector_func(
                                    aggregate,
                                    cast("Iterable[TDomainEvent]", new_events),
                                )
                                if _aggregate is None:
                                    raise AggregateNotFoundError(aggregate_id)
                                aggregate = _aggregate
                            finally:
                                lock.release()
                    finally:
                        self._disuse_fastforward_lock(aggregate_id)

            if deepcopy_from_cache and self.deepcopy_from_cache:
                aggregate = deepcopy(aggregate)
        else:
            aggregate = await self._reconstruct_aggregate(
                aggregate_id, version, projector_func
            )
        return aggregate

    async def _reconstruct_aggregate(
        self,
        aggregate_id: TAggregateID,
        version: int | None,
        projector_func: ProjectorFunction[TMutableOrImmutableAggregate, TDomainEvent],
    ) -> TMutableOrImmutableAggregate:
        gt: int | None = None

        if self.snapshot_store is not None:
            snapshots = list(
                await self.snapshot_store.get(
                    originator_id=aggregate_id,
                    desc=True,
                    limit=1,
                    lte=version,
                )
            )
            if snapshots:
                gt = snapshots[0].originator_version
        else:
            snapshots = []

        aggregate_events = await self.event_store.get(
            originator_id=aggregate_id,
            gt=gt,
            lte=version,
        )

        initial: TMutableOrImmutableAggregate | None = None
        aggregate = projector_func(
            initial,
            chain(
                cast("Iterable[TDomainEvent]", snapshots),
                cast("Iterable[TDomainEvent]", aggregate_events),
            ),
        )

        if aggregate is None:
            msg = f"Aggregate {aggregate_id!r} version {version!r} not found."
            raise AggregateNotFoundError(msg)
        return aggregate

    def _use_fastforward_lock(self, aggregate_id: TAggregateID) -> asyncio.Lock:
        lock: asyncio.Lock | None = None
        num_users = 0
        with contextlib.suppress(KeyError):
            lock, num_users = self._fastforward_locks_inuse[aggregate_id]
        if lock is None:
            with contextlib.suppress(KeyError):
                lock = self._fastforward_locks_cache.get(aggregate_id, evict=True)
        if lock is None:
            lock = asyncio.Lock()
        num_users += 1
        self._fastforward_locks_inuse[aggregate_id] = (lock, num_users)
        return lock

    def _disuse_fastforward_lock(self, aggregate_id: TAggregateID) -> None:
        lock_, num_users = self._fastforward_locks_inuse[aggregate_id]
        num_users -= 1
        if num_users == 0:
            del self._fastforward_locks_inuse[aggregate_id]
            self._fastforward_locks_cache.put(aggregate_id, lock_)
        else:
            self._fastforward_locks_inuse[aggregate_id] = (lock_, num_users)

    async def contains(self, item: TAggregateID) -> bool:
        """Tests to see if an aggregate exists in the repository."""
        try:
            await self.get(aggregate_id=item)
        except AggregateNotFoundError:
            return False
        else:
            return True


class AsyncNotificationLog(ABC):
    """Abstract base class for asynchronous notification logs."""

    @abstractmethod
    async def get_section(self, section_id: str) -> Section:
        """Returns a Section of Notification objects."""

    @abstractmethod
    async def select(
        self,
        start: int | None,
        limit: int,
        stop: int | None = None,
        topics: Sequence[str] = (),
        *,
        inclusive_of_start: bool = True,
    ) -> Sequence[Notification]:
        """Returns a selection of Notification objects."""


class AsyncLocalNotificationLog(AsyncNotificationLog):
    """Asynchronous notification log that presents sections of event
    notifications retrieved from an asynchronous application recorder.
    """

    DEFAULT_SECTION_SIZE = 10

    def __init__(
        self,
        recorder: AsyncApplicationRecorder,
        section_size: int = DEFAULT_SECTION_SIZE,
    ):
        self.recorder = recorder
        self.section_size = section_size

    async def get_section(self, requested_section_id: str) -> Section:
        """Returns a Section of event notifications based on the requested
        section ID.
        """
        parts = requested_section_id.split(",")
        part1 = int(parts[0])
        part2 = int(parts[1])
        start = max(1, part1)
        limit = min(max(0, part2 - start + 1), self.section_size)

        notifications = await self.select(start, limit)

        if len(notifications):
            last_notification_id = notifications[-1].id
            actual_section_id: str | None = self.format_section_id(
                notifications[0].id, last_notification_id
            )
            if len(notifications) == limit:
                next_id: str | None = self.format_section_id(
                    last_notification_id + 1, last_notification_id + limit
                )
            else:
                next_id = None
        else:
            actual_section_id = None
            next_id = None

        return Section(
            id=actual_section_id,
            items=notifications,
            next_id=next_id,
        )

    async def select(
        self,
        start: int | None,
        limit: int,
        stop: int | None = None,
        topics: Sequence[str] = (),
        *,
        inclusive_of_start: bool = True,
    ) -> Sequence[Notification]:
        """Returns a selection of Notification objects from the notification log."""
        if limit > self.section_size:
            msg = (
                f"Requested limit {limit} greater than section size "
                f"{self.section_size}"
            )
            raise ValueError(msg)
        return await self.recorder.select_notifications(
            start=start,
            limit=limit,
            stop=stop,
            topics=topics,
            inclusive_of_start=inclusive_of_start,
        )

    @staticmethod
    def format_section_id(first_id: int, last_id: int) -> str:
        return f"{first_id},{last_id}"


class AsyncApplication(Generic[TAggregateID]):
    """Base class for asynchronous event-sourced applications."""

    name = "Application"
    env: ClassVar[dict[str, str]] = {}
    is_snapshotting_enabled: bool = False
    snapshotting_intervals: ClassVar[
        dict[type[MutableOrImmutableAggregate[Any]], int]
    ] = {}
    snapshotting_projectors: ClassVar[
        dict[
            type[MutableOrImmutableAggregate[Any]],
            ProjectorFunction[Any, Any],
        ]
    ] = {}
    snapshot_class: type[SnapshotProtocol[TAggregateID]] | None = None
    log_section_size = 10
    notify_topics: Sequence[str] = []

    AGGREGATE_CACHE_MAXSIZE = "AGGREGATE_CACHE_MAXSIZE"
    AGGREGATE_CACHE_FASTFORWARD = "AGGREGATE_CACHE_FASTFORWARD"
    AGGREGATE_CACHE_FASTFORWARD_SKIPPING = "AGGREGATE_CACHE_FASTFORWARD_SKIPPING"
    DEEPCOPY_FROM_AGGREGATE_CACHE = "DEEPCOPY_FROM_AGGREGATE_CACHE"

    def __init_subclass__(cls, **kwargs: Any) -> None:
        if "name" not in cls.__dict__:
            cls.name = cls.__name__

    def __init__(self, env: EnvType | None = None) -> None:
        """Initialises an asynchronous application. Call :func:`start` (or use
        the application as an async context manager) before using it.
        """
        self.closing = asyncio.Event()
        self.env = self.construct_env(self.name, env)  # type: ignore[misc]
        self.factory = self.construct_factory(self.env)
        self.mapper: Mapper[TAggregateID] = self.construct_mapper()
        self.recorder = self.construct_recorder()
        self.events: AsyncEventStore[TAggregateID] = self.construct_event_store()
        self.snapshots: AsyncEventStore[TAggregateID] | None = None
        if self.factory.is_snapshotting_enabled():
            self.snapshots = self.construct_snapshot_store()
        self._repository: AsyncRepository[TAggregateID] = self.construct_repository()
        self._notification_log = self.construct_notification_log()
        self._is_started = False
        self._start_lock = asyncio.Lock()

    async def start(self) -> None:
        """Starts the application, opening database connections and
        creating tables if configured to do so.
        """
        if self._is_started:
            return
        async with self._start_lock:
            if self._is_started:
                return
            await self.factory.start()
            self._is_started = True

    async def _ensure_started(self) -> None:
        if not self._is_started:
            await self.start()

    async def aclose(self) -> None:
        """Closes the application and its infrastructure factory."""
        self.closing.set()
        await self.factory.aclose()
        self._is_started = False

    @property
    def repository(self) -> AsyncRepository[TAggregateID]:
        """An application's repository reconstructs aggregates from stored events."""
        return self._repository

    @property
    def notification_log(self) -> AsyncLocalNotificationLog:
        """An application's notification log presents all the aggregate events
        of an application in the order they were recorded.
        """
        return self._notification_log

    def construct_env(self, name: str, env: EnvType | None = None) -> Environment:
        """Constructs environment from which application will be configured."""
        _env = dict(type(self).env)
        if type(self).is_snapshotting_enabled or type(self).snapshotting_intervals:
            _env["IS_SNAPSHOTTING_ENABLED"] = "y"
        _env.update(os.environ)
        if env is not None:
            _env.update(env)
        return Environment(name, _env)

    def construct_factory(self, env: Environment) -> AsyncInfrastructureFactory[Any]:
        """Constructs an asynchronous infrastructure factory."""
        return AsyncInfrastructureFactory.construct(env)

    def construct_mapper(self) -> Mapper[TAggregateID]:
        """Constructs a mapper for use by the application."""
        return self.factory.mapper(transcoder=self.construct_transcoder())

    def construct_transcoder(self) -> Transcoder:
        """Constructs a transcoder for use by the application."""
        transcoder = self.factory.transcoder()
        if isinstance(transcoder, JSONTranscoder):
            self.register_transcodings(transcoder)
        return transcoder

    def register_transcodings(self, transcoder: JSONTranscoder) -> None:
        """Registers transcodings on the given JSON transcoder."""
        transcoder.register(UUIDAsHex())
        transcoder.register(DecimalAsStr())
        transcoder.register(DatetimeAsISO())

    def construct_recorder(self) -> AsyncApplicationRecorder:
        """Constructs an asynchronous application recorder."""
        return self.factory.application_recorder()

    def construct_event_store(self) -> AsyncEventStore[TAggregateID]:
        """Constructs an asynchronous event store."""
        return self.factory.event_store(
            mapper=self.mapper,
            recorder=self.recorder,
        )

    def construct_snapshot_store(self) -> AsyncEventStore[TAggregateID]:
        """Constructs an asynchronous snapshot event store."""
        recorder = self.factory.aggregate_recorder(purpose="snapshots")
        return self.factory.event_store(
            mapper=self.mapper,
            recorder=recorder,
        )

    def construct_repository(self) -> AsyncRepository[TAggregateID]:
        """Constructs an asynchronous repository."""
        cache_maxsize_envvar = self.env.get(self.AGGREGATE_CACHE_MAXSIZE)
        cache_maxsize = int(cache_maxsize_envvar) if cache_maxsize_envvar else None
        return AsyncRepository(
            event_store=self.events,
            snapshot_store=self.snapshots,
            cache_maxsize=cache_maxsize,
            fastforward=strtobool(self.env.get(self.AGGREGATE_CACHE_FASTFORWARD, "y")),
            fastforward_skipping=strtobool(
                self.env.get(self.AGGREGATE_CACHE_FASTFORWARD_SKIPPING, "n")
            ),
            deepcopy_from_cache=strtobool(
                self.env.get(self.DEEPCOPY_FROM_AGGREGATE_CACHE, "y")
            ),
        )

    def construct_notification_log(self) -> AsyncLocalNotificationLog:
        """Constructs an async local notification log."""
        return AsyncLocalNotificationLog(
            self.recorder, section_size=self.log_section_size
        )

    async def save(
        self,
        *objs: MutableOrImmutableAggregate[TAggregateID]
        | DomainEventProtocol[TAggregateID]
        | None,
        **kwargs: Any,
    ) -> list[Recording[TAggregateID]]:
        """Collects pending events from given aggregates and puts them in the
        application's event store.
        """
        await self._ensure_started()
        processing_event: ProcessingEvent[TAggregateID] = ProcessingEvent()
        processing_event.collect_events(*objs, **kwargs)
        recordings = await self._record(processing_event)
        await self._take_snapshots(processing_event)
        self._notify(recordings)
        self.notify(processing_event.events)
        return recordings

    async def _record(
        self, processing_event: ProcessingEvent[TAggregateID]
    ) -> list[Recording[TAggregateID]]:
        recordings = await self.events.put(
            processing_event.events,
            tracking=processing_event.tracking,
            **processing_event.saved_kwargs,
        )
        if self.repository.cache and not self.repository.fastforward:
            for aggregate_id, aggregate in processing_event.aggregates.items():
                self.repository.cache.put(aggregate_id, aggregate)
        return recordings

    async def _take_snapshots(
        self, processing_event: ProcessingEvent[TAggregateID]
    ) -> None:
        if self.snapshots and self.snapshotting_intervals:
            for event in processing_event.events:
                try:
                    aggregate = processing_event.aggregates[event.originator_id]
                except KeyError:
                    continue
                interval = self.snapshotting_intervals.get(type(aggregate))
                if interval is not None and event.originator_version % interval == 0:
                    try:
                        projector_func = self.snapshotting_projectors[type(aggregate)]
                    except KeyError:
                        if not isinstance(event, CanMutateProtocol):
                            msg = (
                                "Cannot take snapshot for "
                                f"{type(aggregate)} with default "
                                "project_aggregate() function, because its domain "
                                f"event {type(event)} does not implement the "
                                "'can mutate' protocol (see CanMutateProtocol). "
                                f"Please define application class {type(self)} with "
                                "class variable 'snapshotting_projectors', to be a "
                                f"dict that has {type(aggregate)} as a key with the "
                                "aggregate projector function for "
                                f"{type(aggregate)} as the value for that key."
                            )
                            raise ProgrammingError(msg) from None
                        projector_func = project_aggregate
                    await self.take_snapshot(
                        aggregate_id=event.originator_id,
                        version=event.originator_version,
                        projector_func=projector_func,
                    )

    async def take_snapshot(
        self,
        aggregate_id: TAggregateID,
        version: int | None = None,
        projector_func: ProjectorFunction[Any, Any] = project_aggregate,
    ) -> None:
        """Takes a snapshot of the recorded state of the aggregate."""
        if self.snapshots is None:
            msg = (
                "Can't take snapshot without snapshots store. Please "
                "set environment variable IS_SNAPSHOTTING_ENABLED to "
                "a true value (e.g. 'y'), or set 'is_snapshotting_enabled' "
                "on application class, or set 'snapshotting_intervals' on "
                "application class."
            )
            raise AssertionError(msg)
        aggregate: BaseAggregate[TAggregateID] = await self.repository.get(
            aggregate_id, version=version, projector_func=projector_func
        )
        snapshot_class = getattr(type(aggregate), "Snapshot", type(self).snapshot_class)
        if snapshot_class is None:
            msg = (
                "Neither application nor aggregate have a snapshot class. "
                f"Please either define a nested 'Snapshot' class on "
                f"{type(aggregate)} or set class attribute 'snapshot_class' on "
                f"{type(self)}."
            )
            raise AssertionError(msg)

        snapshot = snapshot_class.take(aggregate)
        await self.snapshots.put([snapshot])

    def notify(self, new_events: list[Any]) -> None:
        """Deprecated hook called after new aggregate events have been saved."""

    def _notify(self, recordings: list[Recording[TAggregateID]]) -> None:
        """Hook called after new aggregate events have been saved."""

    async def __aenter__(self) -> Self:
        await self.start()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        await self.aclose()
