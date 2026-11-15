from __future__ import annotations

import asyncio
import contextlib
import os
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Sequence
from typing import TYPE_CHECKING, Any, Generic, TypeVar, cast

from eventsourcing.application import ProcessingEvent
from etlalchemy._vendor.eventsourcing.asyncio.application import AsyncApplication
from etlalchemy._vendor.eventsourcing.asyncio.persistence import (
    AsyncInfrastructureFactory,
    AsyncProcessRecorder,
    AsyncTrackingRecorder,
)
from eventsourcing.dispatch import singledispatchmethod
from eventsourcing.domain import DomainEventProtocol, TAggregateID
from eventsourcing.persistence import (
    Mapper,
    Tracking,
    WaitInterruptedError,
)
from eventsourcing.utils import Environment, EnvType

if TYPE_CHECKING:
    from types import TracebackType
    from typing import Self


TAsyncTrackingRecorder = TypeVar("TAsyncTrackingRecorder", bound=AsyncTrackingRecorder)
TApplication = TypeVar("TApplication", bound=AsyncApplication[Any])
TAsyncEventSourcedProjection = TypeVar(
    "TAsyncEventSourcedProjection", bound="AsyncEventSourcedProjection[Any]"
)


class AsyncApplicationSubscription(
    AsyncIterator[tuple[DomainEventProtocol[TAggregateID], Tracking]]
):
    """An asynchronous iterator that yields domain events recorded in an
    application sequence, together with tracking objects.
    """

    def __init__(
        self,
        app: AsyncApplication[TAggregateID],
        gt: int | None = None,
        topics: Sequence[str] = (),
    ):
        self.name = app.name
        self.recorder = app.recorder
        self.mapper: Mapper[TAggregateID] = app.mapper
        self.subscription = self.recorder.subscribe(gt=gt, topics=topics)

    async def stop(self) -> None:
        """Stops the subscription to the application's recorder."""
        await self.subscription.stop()

    async def __aenter__(self) -> Self:
        await self.subscription.__aenter__()
        return self

    async def __aexit__(self, *args: object, **kwargs: Any) -> None:
        await self.subscription.__aexit__(*args, **kwargs)

    def __aiter__(self) -> Self:
        return self

    async def __anext__(
        self,
    ) -> tuple[DomainEventProtocol[TAggregateID], Tracking]:
        notification = await self.subscription.__anext__()
        tracking = Tracking(self.name, notification.id)
        domain_event = self.mapper.to_domain_event(notification)
        return domain_event, tracking


class AsyncProjection(ABC, Generic[TAsyncTrackingRecorder]):
    name: str = ""
    """Name of projection, used to pick prefixed environment
    variables and define database table names.
    """
    topics: tuple[str, ...] = ()

    def __init_subclass__(cls, **kwargs: Any) -> None:
        if "name" not in cls.__dict__:
            cls.name = cls.__name__

    def __init__(
        self,
        view: TAsyncTrackingRecorder,
    ):
        self._view = view

    @property
    def view(self) -> TAsyncTrackingRecorder:
        """Materialised view of an event-sourced application."""
        return self._view

    @singledispatchmethod
    @abstractmethod
    async def process_event(self, domain_event: Any, tracking: Tracking) -> None:
        """Process a domain event and track it."""


class AsyncEventSourcedProjection(AsyncApplication[TAggregateID], ABC):
    """Extends :class:`AsyncApplication` by using a process recorder as its
    application recorder, and by processing domain events through its
    :func:`policy` method.
    """

    topics: Sequence[str] = ()

    def __init__(self, env: EnvType | None = None) -> None:
        super().__init__(env)
        self.recorder: AsyncProcessRecorder
        self.processing_lock = asyncio.Lock()

    def construct_recorder(self) -> AsyncProcessRecorder:
        """Constructs an asynchronous process recorder."""
        return self.factory.process_recorder()

    async def process_event(
        self, domain_event: DomainEventProtocol[TAggregateID], tracking: Tracking
    ) -> None:
        """Calls the policy method with the given domain event and a new
        ProcessingEvent constructed with the given tracking object.
        """
        processing_event = ProcessingEvent[TAggregateID](tracking=tracking)
        await self.policy(domain_event, processing_event)
        recordings = await self._record(processing_event)
        await self._take_snapshots(processing_event)
        self.notify(processing_event.events)
        self._notify(recordings)

    @singledispatchmethod
    async def policy(
        self,
        domain_event: DomainEventProtocol[TAggregateID],
        processing_event: ProcessingEvent[TAggregateID],
    ) -> None:
        """Domain event processing policy method."""


class AsyncBaseProjectionRunner(Generic[TApplication]):
    """Base class for asynchronous projection runners."""

    def __init__(self) -> None:
        self._is_interrupted = asyncio.Event()
        self._has_called_stop = False
        self._thread_error: BaseException | None = None
        self._processing_task: asyncio.Task[None] | None = None
        self._subscription: AsyncApplicationSubscription[Any] | None = None
        self._tracking_recorder: AsyncTrackingRecorder | None = None
        self._projection: AsyncProjection[Any] | AsyncEventSourcedProjection[Any]
        self._projection_app: AsyncApplication[Any] | None = None
        self._projection_factory: AsyncInfrastructureFactory[Any] | None = None
        self.app: TApplication
        self.app_name = ""

    @property
    def is_interrupted(self) -> asyncio.Event:
        return self._is_interrupted

    @staticmethod
    def _construct_env(name: str, env: EnvType | None = None) -> Environment:
        _env: dict[str, str] = {}
        _env.update(os.environ)
        if env is not None:
            _env.update(env)
        return Environment(name, _env)

    async def start(self) -> None:
        """Starts processing events in a new asyncio task."""
        self._processing_task = asyncio.create_task(self._process_events_loop())

    async def stop(self) -> None:
        """Stops the subscription and the event-processing task."""
        self._has_called_stop = True
        self._is_interrupted.set()
        if self._subscription is not None:
            await self._subscription.stop()
        if self._processing_task is not None:
            with contextlib.suppress(asyncio.CancelledError):
                await self._processing_task
            self._processing_task = None
        await self.app.aclose()
        if self._projection_app is not None:
            await self._projection_app.aclose()
        if self._projection_factory is not None:
            await self._projection_factory.aclose()

    async def _process_events_loop(self) -> None:
        """Iterates over the subscription and calls process_event()."""
        assert self._subscription is not None
        try:
            async for domain_event, tracking in self._subscription:
                await self._projection.process_event(domain_event, tracking)
        except asyncio.CancelledError:
            raise
        except BaseException as e:
            self._thread_error = e
        finally:
            self._is_interrupted.set()

    async def run_forever(self, timeout: float | None = None) -> None:  # noqa: ASYNC109
        """Blocks until timeout, or until the runner is stopped or errors."""
        try:
            await asyncio.wait_for(self._is_interrupted.wait(), timeout)
        except TimeoutError:
            return
        if self._thread_error is not None:
            error = self._thread_error
            self._thread_error = None
            raise error

    async def wait(
        self, notification_id: int | None, timeout: float = 1.0  # noqa: ASYNC109
    ) -> None:
        """Waits until the materialised view has recorded a tracking object
        that is greater than or equal to the given notification ID.
        """
        assert self._tracking_recorder is not None
        try:
            await self._tracking_recorder.wait(
                application_name=self.app_name,
                notification_id=notification_id,
                timeout=timeout,
                interrupt=self._is_interrupted,
            )
        except WaitInterruptedError:
            if self._thread_error is not None:
                error = self._thread_error
                self._thread_error = None
                raise error from None
            if self._has_called_stop:
                return
            raise

    async def __aenter__(self) -> Self:
        await self.start()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        await self.stop()
        if self._thread_error is not None:
            error = self._thread_error
            self._thread_error = None
            raise error


class AsyncProjectionRunner(
    AsyncBaseProjectionRunner[TApplication],
    Generic[TApplication, TAsyncTrackingRecorder],
):
    def __init__(
        self,
        *,
        application_class: type[TApplication],
        projection_class: type[AsyncProjection[TAsyncTrackingRecorder]],
        view_class: type[TAsyncTrackingRecorder],
        env: EnvType | None = None,
    ) -> None:
        super().__init__()
        self._application_class = application_class
        self._projection_class = projection_class
        self._view_class = view_class
        self._env = env
        self.view: TAsyncTrackingRecorder
        self.projection: AsyncProjection[TAsyncTrackingRecorder]

    async def start(self) -> None:
        """Constructs the view, projection, and application, then starts
        processing events.
        """
        factory = AsyncInfrastructureFactory.construct(
            env=self._construct_env(name=self._projection_class.name, env=self._env)
        )
        view = cast(TAsyncTrackingRecorder, factory.tracking_recorder(self._view_class))
        await factory.start()
        self.view = view
        self._projection_factory = factory

        projection = self._projection_class(view=view)
        self.projection = projection

        app = self._application_class(self._env)
        await app.start()
        self.app = app
        self.app_name = app.name
        self._projection = cast(Any, projection)
        self._tracking_recorder = view
        self._subscription = AsyncApplicationSubscription(
            app=app,
            gt=await view.max_tracking_id(app.name),
            topics=projection.topics,
        )
        await super().start()


class AsyncEventSourcedProjectionRunner(
    AsyncBaseProjectionRunner[TApplication],
    Generic[TApplication, TAsyncEventSourcedProjection],
):
    def __init__(
        self,
        *,
        application_class: type[TApplication],
        projection_class: type[TAsyncEventSourcedProjection],
        env: EnvType | None = None,
    ) -> None:
        super().__init__()
        self._application_class = application_class
        self._projection_class = projection_class
        self._env = env
        self.projection: TAsyncEventSourcedProjection

    async def start(self) -> None:
        """Constructs the projection and application, then starts processing
        events.
        """
        projection = self._projection_class(
            env=self._construct_env(name=self._projection_class.name, env=self._env)
        )
        await projection.start()
        self.projection = projection
        self._projection_app = projection

        app = self._application_class(self._env)
        await app.start()
        self.app = app
        self.app_name = app.name
        self._projection = cast(Any, projection)
        self._tracking_recorder = projection.recorder
        self._subscription = AsyncApplicationSubscription(
            app=app,
            gt=await projection.recorder.max_tracking_id(app.name),
            topics=projection.topics,
        )
        await super().start()
