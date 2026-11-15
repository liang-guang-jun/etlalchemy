from __future__ import annotations

import asyncio
import contextlib
import typing
from abc import ABC, abstractmethod
from time import monotonic
from types import ModuleType
from typing import TYPE_CHECKING, Any, Generic, Self

from typing_extensions import TypeVar

from eventsourcing.domain import DomainEventProtocol, TAggregateID
from eventsourcing.persistence import (
    Cipher,
    Compressor,
    InfrastructureFactoryError,
    JSONTranscoder,
    Mapper,
    Notification,
    Recording,
    StoredEvent,
    Tracking,
    Transcoder,
    WaitInterruptedError,
)
from eventsourcing.utils import (
    Environment,
    EnvType,
    TopicError,
    resolve_topic,
    strtobool,
)

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence
    from types import TracebackType


class AsyncRecorder:
    """Base class for asynchronous recorders."""


class AsyncAggregateRecorder(AsyncRecorder, ABC):
    """Abstract base class for asynchronously inserting and selecting stored events."""

    @abstractmethod
    async def insert_events(
        self, stored_events: Sequence[StoredEvent], **kwargs: Any
    ) -> Sequence[int] | None:
        """Writes stored events into database."""

    @abstractmethod
    async def select_events(
        self,
        originator_id: Any,
        *,
        gt: int | None = None,
        lte: int | None = None,
        desc: bool = False,
        limit: int | None = None,
    ) -> Sequence[StoredEvent]:
        """Reads stored events from database."""


class AsyncApplicationRecorder(AsyncAggregateRecorder):
    """Abstract base class for asynchronously recording events in both aggregate
    and application sequences.
    """

    @abstractmethod
    async def select_notifications(
        self,
        start: int | None,
        limit: int,
        stop: int | None = None,
        topics: Sequence[str] = (),
        *,
        inclusive_of_start: bool = True,
    ) -> Sequence[Notification]:
        """Returns a list of Notification objects from an application sequence."""

    @abstractmethod
    async def max_notification_id(self) -> int | None:
        """Returns the largest notification ID in an application sequence."""

    def subscribe(
        self, gt: int | None = None, topics: Sequence[str] = ()
    ) -> AsyncSubscription[Any]:
        """Returns an async iterator of Notification objects."""
        return AsyncPollingSubscription(self, gt=gt, topics=topics)


class AsyncTrackingRecorder(AsyncRecorder, ABC):
    """Abstract base class for asynchronously recording tracking objects."""

    @abstractmethod
    async def insert_tracking(self, tracking: Tracking) -> None:
        """Records a tracking object."""

    @abstractmethod
    async def max_tracking_id(self, application_name: str) -> int | None:
        """Returns the largest notification ID for the named application."""

    async def has_tracking_id(
        self, application_name: str, notification_id: int | None
    ) -> bool:
        """Returns True if the given notification ID has been tracked."""
        if notification_id is None:
            return True
        max_tracking_id = await self.max_tracking_id(application_name)
        return max_tracking_id is not None and max_tracking_id >= notification_id

    async def wait(
        self,
        application_name: str,
        notification_id: int | None,
        timeout: float = 1.0,  # noqa: ASYNC109
        interrupt: asyncio.Event | None = None,
    ) -> None:
        """Waits until a tracking object has been recorded.

        Raises TimeoutError if the timeout is reached, and
        WaitInterruptedError if the interrupt event is set.
        """
        deadline = monotonic() + timeout
        sleep_interval_ms = 100.0
        max_sleep_interval_ms = 800.0
        while True:
            if await self.has_tracking_id(application_name, notification_id):
                break
            remaining = deadline - monotonic()
            if remaining < 0:
                msg = (
                    f"Timed out waiting for notification {notification_id} "
                    f"from application '{application_name}' to be processed"
                )
                raise TimeoutError(msg)
            sleep_interval_ms = min(sleep_interval_ms * 2, max_sleep_interval_ms)
            interval = min(sleep_interval_ms, remaining * 1000) / 1000
            if interrupt is not None:
                try:
                    await asyncio.wait_for(interrupt.wait(), timeout=interval)
                except TimeoutError:
                    continue
                raise WaitInterruptedError
            await asyncio.sleep(interval)


class AsyncProcessRecorder(AsyncTrackingRecorder, AsyncApplicationRecorder, ABC):
    """Abstract base class for asynchronously recording tracking objects
    atomically with new stored events.
    """


TAsyncApplicationRecorder = TypeVar(
    "TAsyncApplicationRecorder",
    bound=AsyncApplicationRecorder,
    default=AsyncApplicationRecorder,
)
TAsyncApplicationRecorder_co = TypeVar(
    "TAsyncApplicationRecorder_co",
    bound=AsyncApplicationRecorder,
    covariant=True,
)


class AsyncSubscription(ABC, Generic[TAsyncApplicationRecorder_co]):
    """Abstract base class for asynchronous subscriptions to an
    application sequence.
    """

    def __init__(
        self,
        recorder: TAsyncApplicationRecorder_co,
        gt: int | None = None,
        topics: Sequence[str] = (),
    ) -> None:
        self._recorder = recorder
        self._last_notification_id = gt
        self._topics = topics
        self._has_been_entered = False
        self._stopped = asyncio.Event()

    async def __aenter__(self) -> Self:
        if self._has_been_entered:
            msg = "Already entered subscription context manager"
            raise RuntimeError(msg)
        self._has_been_entered = True
        return self

    async def __aexit__(self, *args: object, **kwargs: Any) -> None:
        await self.stop()

    async def stop(self) -> None:
        """Stops the subscription."""
        self._stopped.set()

    def __aiter__(self) -> Self:
        return self

    @abstractmethod
    async def __anext__(self) -> Notification:
        """Returns the next Notification object in the application sequence."""


class AsyncPollingSubscription(AsyncSubscription[TAsyncApplicationRecorder_co]):
    """Asynchronous subscription that polls the recorder for new notifications."""

    def __init__(
        self,
        recorder: TAsyncApplicationRecorder_co,
        gt: int | None = None,
        topics: Sequence[str] = (),
        poll_interval: float = 0.05,
    ) -> None:
        super().__init__(recorder=recorder, gt=gt, topics=topics)
        self._poll_interval = poll_interval
        self._select_limit = 500
        self._notifications: Sequence[Notification] = []
        self._notifications_index = 0

    async def __anext__(self) -> Notification:
        while True:
            if self._notifications_index < len(self._notifications):
                notification = self._notifications[self._notifications_index]
                self._notifications_index += 1
                return notification

            if self._stopped.is_set():
                raise StopAsyncIteration

            notifications = await self._recorder.select_notifications(
                start=self._last_notification_id or 0,
                limit=self._select_limit,
                topics=self._topics,
                inclusive_of_start=False,
            )
            if notifications:
                self._notifications = notifications
                self._notifications_index = 0
                self._last_notification_id = notifications[-1].id
                continue

            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(
                    self._stopped.wait(), timeout=self._poll_interval
                )


class AsyncEventStore(Generic[TAggregateID]):
    """Stores and retrieves domain events asynchronously."""

    def __init__(
        self,
        mapper: Mapper[TAggregateID],
        recorder: AsyncAggregateRecorder,
    ):
        self.mapper: Mapper[TAggregateID] = mapper
        self.recorder = recorder

    async def put(
        self, domain_events: Sequence[DomainEventProtocol[TAggregateID]], **kwargs: Any
    ) -> list[Recording[TAggregateID]]:
        """Stores domain events in aggregate sequence."""
        stored_events = list(map(self.mapper.to_stored_event, domain_events))
        recordings: list[Recording[TAggregateID]] = []
        notification_ids = await self.recorder.insert_events(stored_events, **kwargs)
        if notification_ids:
            assert len(notification_ids) == len(stored_events)
            for d, s, n_id in zip(
                domain_events, stored_events, notification_ids, strict=True
            ):
                recordings.append(
                    Recording(
                        d,
                        Notification(
                            originator_id=s.originator_id,
                            originator_version=s.originator_version,
                            topic=s.topic,
                            state=s.state,
                            id=n_id,
                        ),
                    )
                )
        return recordings

    async def get(
        self,
        originator_id: TAggregateID,
        *,
        gt: int | None = None,
        lte: int | None = None,
        desc: bool = False,
        limit: int | None = None,
    ) -> Iterator[DomainEventProtocol[TAggregateID]]:
        """Retrieves domain events from aggregate sequence."""
        stored_events = await self.recorder.select_events(
            originator_id=originator_id,
            gt=gt,
            lte=lte,
            desc=desc,
            limit=limit,
        )
        return map(self.mapper.to_domain_event, stored_events)


TAsyncTrackingRecorder = TypeVar(
    "TAsyncTrackingRecorder",
    bound=AsyncTrackingRecorder,
    default=AsyncTrackingRecorder,
)


class AsyncBaseInfrastructureFactory(ABC, Generic[TAsyncTrackingRecorder]):
    """Abstract base class for asynchronous infrastructure factories."""

    PERSISTENCE_MODULE = "PERSISTENCE_MODULE"
    TRANSCODER_TOPIC = "TRANSCODER_TOPIC"
    CIPHER_TOPIC = "CIPHER_TOPIC"
    COMPRESSOR_TOPIC = "COMPRESSOR_TOPIC"

    def __init__(self, env: Environment | EnvType | None):
        self.env = env if isinstance(env, Environment) else Environment(env=env)
        self._is_started = False

    async def start(self) -> None:
        """Starts the factory, opening any resources needed by recorders."""
        self._is_started = True

    async def aclose(self) -> None:
        """Closes any resources held by the factory."""
        self._is_started = False

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

    @classmethod
    def construct(
        cls: type[Self],
        env: Environment | EnvType | None = None,
    ) -> Self:
        """Constructs a concrete asynchronous infrastructure factory for the
        given named application. Reads and resolves the persistence topic from
        the environment variable 'PERSISTENCE_MODULE'.
        """
        factory_cls: type[Self]
        if env is None:
            env = Environment()
        elif not isinstance(env, Environment):
            env = Environment(env=env)
        topic = (
            env.get(cls.PERSISTENCE_MODULE, "")
            or env.get("INFRASTRUCTURE_FACTORY", "")
            or env.get("FACTORY_TOPIC", "")
            or "etlalchemy._vendor.eventsourcing.asyncio.sqlalchemy"
        )
        try:
            obj: type[Self] | ModuleType = resolve_topic(topic)
        except TopicError as e:
            msg = (
                "Failed to resolve persistence module topic: "
                f"'{topic}' from environment "
                f"variable '{cls.PERSISTENCE_MODULE}'"
            )
            raise InfrastructureFactoryError(msg) from e

        if isinstance(obj, ModuleType):
            factory_classes = set[type[Self]]()
            for member in obj.__dict__.values():
                if not isinstance(member, type):
                    continue
                if not issubclass(member, cls):
                    continue
                if getattr(member, "__parameters__", None):
                    continue
                factory_classes.add(member)

            if len(factory_classes) == 1:
                factory_cls = next(iter(factory_classes))
            else:
                msg = (
                    f"Found {len(factory_classes)} infrastructure factory classes in"
                    f" '{topic}', expected 1."
                )
                raise InfrastructureFactoryError(msg)
        elif isinstance(obj, type) and issubclass(obj, cls):
            factory_cls = obj
        else:
            msg = (
                f"Topic '{topic}' didn't resolve to a persistence module "
                f"or infrastructure factory class: {obj}"
            )
            raise InfrastructureFactoryError(msg)
        return factory_cls(env=env)

    def transcoder(self) -> Transcoder:
        """Constructs a transcoder."""
        transcoder_topic = self.env.get(self.TRANSCODER_TOPIC)
        if transcoder_topic:
            transcoder_class: type[Transcoder] = resolve_topic(transcoder_topic)
        else:
            transcoder_class = JSONTranscoder
        return transcoder_class()

    def cipher(self) -> Cipher | None:
        """Constructs an optional cipher from the environment."""
        cipher_topic = self.env.get(self.CIPHER_TOPIC)
        cipher: Cipher | None = None
        default_cipher_topic = "eventsourcing.cipher:AESCipher"
        if self.env.get("CIPHER_KEY") and not cipher_topic:
            cipher_topic = default_cipher_topic
        if cipher_topic:
            cipher_cls: type[Cipher] = resolve_topic(cipher_topic)
            cipher = cipher_cls(self.env)
        return cipher

    def compressor(self) -> Compressor | None:
        """Constructs an optional compressor from the environment."""
        compressor: Compressor | None = None
        compressor_topic = self.env.get(self.COMPRESSOR_TOPIC)
        if compressor_topic:
            compressor_cls: type[Compressor] | Compressor = resolve_topic(
                compressor_topic
            )
            if isinstance(compressor_cls, type):
                compressor = compressor_cls()
            else:
                compressor = compressor_cls
        return compressor


class AsyncInfrastructureFactory(
    AsyncBaseInfrastructureFactory[TAsyncTrackingRecorder]
):
    """Abstract base class for asynchronous application factories."""

    MAPPER_TOPIC = "MAPPER_TOPIC"
    IS_SNAPSHOTTING_ENABLED = "IS_SNAPSHOTTING_ENABLED"
    APPLICATION_RECORDER_TOPIC = "APPLICATION_RECORDER_TOPIC"
    TRACKING_RECORDER_TOPIC = "TRACKING_RECORDER_TOPIC"
    PROCESS_RECORDER_TOPIC = "PROCESS_RECORDER_TOPIC"

    def mapper(
        self,
        transcoder: Transcoder | None = None,
        mapper_class: type[Mapper[TAggregateID]] | None = None,
    ) -> Mapper[TAggregateID]:
        """Constructs a mapper."""
        if mapper_class is None:
            mapper_topic = self.env.get(self.MAPPER_TOPIC)
            mapper_class = (
                resolve_topic(mapper_topic) if mapper_topic else Mapper[TAggregateID]
            )
        assert mapper_class is not None
        origin_mapper_class = typing.get_origin(mapper_class) or mapper_class
        assert isinstance(origin_mapper_class, type), mapper_class
        assert issubclass(origin_mapper_class, Mapper), mapper_class
        return mapper_class(
            transcoder=transcoder or self.transcoder(),
            cipher=self.cipher(),
            compressor=self.compressor(),
        )

    def event_store(
        self,
        mapper: Mapper[TAggregateID] | None = None,
        recorder: AsyncAggregateRecorder | None = None,
    ) -> AsyncEventStore[TAggregateID]:
        """Constructs an asynchronous event store."""
        return AsyncEventStore(
            mapper=mapper or self.mapper(),
            recorder=recorder or self.application_recorder(),
        )

    @abstractmethod
    def aggregate_recorder(self, purpose: str = "events") -> AsyncAggregateRecorder:
        """Constructs an aggregate recorder."""

    @abstractmethod
    def application_recorder(self) -> AsyncApplicationRecorder:
        """Constructs an application recorder."""

    @abstractmethod
    def tracking_recorder(
        self,
        tracking_recorder_class: type[TAsyncTrackingRecorder] | None = None,
    ) -> TAsyncTrackingRecorder:
        """Constructs a tracking recorder."""

    @abstractmethod
    def process_recorder(self) -> AsyncProcessRecorder:
        """Constructs a process recorder."""

    def is_snapshotting_enabled(self) -> bool:
        """Decides whether snapshotting is enabled."""
        return strtobool(self.env.get(self.IS_SNAPSHOTTING_ENABLED, "no"))
