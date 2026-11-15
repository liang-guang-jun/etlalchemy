"""Projection base that logs the events it materialises.

The read-model views stay silent on purpose: ``projection/sqlite.py`` and
``projection/postgres.py`` run once per projected event and once per read, so a
log line there would only duplicate the event stream or the delivery layer. The
projection is where attribution matters, so the log lives here.
"""

from __future__ import annotations

from typing import Any, TypeVar

from eventsourcing.dispatch import singledispatchmethod
from eventsourcing.persistence import Tracking
from eventsourcing.utils import get_topic

from etlalchemy._vendor.eventsourcing.asyncio.persistence import AsyncTrackingRecorder
from etlalchemy._vendor.eventsourcing.asyncio.projection import AsyncProjection
from etlalchemy.shared.logging import get_logger

TView = TypeVar("TView", bound=AsyncTrackingRecorder)
"""Asynchronous read-model type of the projection."""


class AsyncLoggedProjection(AsyncProjection[TView]):
    """Logs every projected event and any failure before re-raising it.

    Subclasses register their coroutine handlers on :meth:`dispatch_event` with
    ``@dispatch_event.register`` and set :attr:`logger_name`; the framework awaits
    :meth:`process_event`, which wraps that dispatch.
    """

    logger_name = "projection"
    """Logger name passed to :func:`etlalchemy.shared.logging.get_logger`."""

    async def process_event(self, domain_event: Any, tracking: Tracking) -> None:
        """Logs the event, dispatches it, and logs a failure before re-raising.

        Args:
            domain_event: The domain event the follower read from the log.
            tracking: Position the view records together with the change.
        """
        log = get_logger(self.logger_name)
        topic = get_topic(type(domain_event))
        context: dict[str, Any] = {
            "topic": topic,
            "notification_id": tracking.notification_id,
            "originator_id": str(domain_event.originator_id),
        }
        log.debug("projection.event", **context)
        try:
            await self.dispatch_event(domain_event, tracking)
        except Exception:
            log.exception("projection.event.failed", **context)
            raise

    @singledispatchmethod
    async def dispatch_event(self, domain_event: Any, tracking: Tracking) -> None:
        """Ignores events that no handler is registered for."""
