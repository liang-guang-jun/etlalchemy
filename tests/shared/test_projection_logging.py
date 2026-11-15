"""Tests for the projection base that logs the events it materialises."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

import pytest
from eventsourcing.dispatch import singledispatchmethod
from eventsourcing.domain import DomainEvent
from eventsourcing.persistence import Tracking
from eventsourcing.utils import get_topic
from structlog.testing import capture_logs

from etlalchemy.shared.logging import reset_logging
from etlalchemy.shared.projection import AsyncLoggedProjection


class OtherEvent(DomainEvent):
    """Event the demo projection knows how to handle."""


class RecordingView:
    """Records the events the projection hands over."""

    def __init__(self, fail: bool = False) -> None:
        self.handled: list[DomainEvent] = []
        self.fail = fail

    async def record(self, event: DomainEvent) -> None:
        """Records the event, or raises when the view is configured to fail."""
        if self.fail:
            msg = "view exploded"
            raise RuntimeError(msg)
        self.handled.append(event)


class DemoProjection(AsyncLoggedProjection[Any]):
    """Projection with a single registered handler."""

    logger_name = "demo.projection"

    @singledispatchmethod
    async def dispatch_event(self, domain_event: Any, tracking: Tracking) -> None:
        """Ignores events without a registered handler."""

    @dispatch_event.register
    async def _when_other_event(self, event: OtherEvent, tracking: Tracking) -> None:
        """Forwards the event to the view."""
        del tracking
        await self.view.record(event)


def make_event() -> OtherEvent:
    """Returns a domain event carrying the fields the projection logs."""
    return OtherEvent(
        originator_id=uuid4(),
        originator_version=1,
        timestamp=datetime.now(timezone.utc),
    )


@pytest.fixture(autouse=True)
def _logging() -> None:
    """Drops cached loggers so ``capture_logs`` sees the projection output."""
    reset_logging()


async def test_event_is_logged_at_debug() -> None:
    """The dispatch is visible at debug level with the tracking position."""
    view = RecordingView()
    projection = DemoProjection(view)
    event = make_event()

    with capture_logs() as logs:
        await projection.process_event(event, Tracking("demo", 12))

    assert logs == [
        {
            "event": "projection.event",
            "log_level": "debug",
            "topic": get_topic(OtherEvent),
            "notification_id": 12,
            "originator_id": str(event.originator_id),
        }
    ]
    assert view.handled == [event]


async def test_failed_event_is_logged_and_reraised() -> None:
    """A view failure is logged with its event context, then re-raised."""
    projection = DemoProjection(RecordingView(fail=True))

    with capture_logs() as logs, pytest.raises(RuntimeError, match="view exploded"):
        await projection.process_event(make_event(), Tracking("demo", 13))

    assert [entry["event"] for entry in logs] == [
        "projection.event",
        "projection.event.failed",
    ]
    assert logs[-1]["log_level"] == "error"
    assert logs[-1]["notification_id"] == 13


async def test_unhandled_event_is_logged_without_failing() -> None:
    """An event without a registered handler is logged and skipped."""
    projection = DemoProjection(RecordingView())
    event = DomainEvent(
        originator_id=uuid4(),
        originator_version=1,
        timestamp=datetime.now(timezone.utc),
    )

    with capture_logs() as logs:
        await projection.process_event(event, Tracking("demo", 14))

    assert [entry["event"] for entry in logs] == ["projection.event"]
    assert logs[0]["topic"] == get_topic(DomainEvent)
