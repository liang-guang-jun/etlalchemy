"""Tests for the SourceConnection aggregate."""

from dataclasses import FrozenInstanceError, is_dataclass
from typing import Any

import pytest
from etlalchemy.ingestion.aggregates.connection import SourceConnection
from etlalchemy.ingestion.aggregates.errors import DiscardedError, IngestionError

EVENT_CLASSES = [
    SourceConnection.Started,
    SourceConnection.Changed,
    SourceConnection.CredentialRotated,
    SourceConnection.Discarded,
]


def replay(events: list[Any]) -> SourceConnection:
    """Rebuilds a connection by applying the given events in order."""
    aggregate: Any = None
    for event in events:
        aggregate = event.mutate(aggregate)
    assert isinstance(aggregate, SourceConnection)
    return aggregate


def connection(**overrides: Any) -> SourceConnection:
    """Returns a connection with sensible defaults for the given overrides."""
    values: dict[str, Any] = {
        "name": "warehouse",
        "kind": "databricks",
        "endpoint": "https://example.cloud.databricks.com",
        "token": "s3cr3t",
    }
    values.update(overrides)
    return SourceConnection(**values)


def test_creating_a_connection_records_a_started_event() -> None:
    """Creating a connection stores its metadata and records Started."""
    created = connection(default_catalog="main", options={"warehouse_id": "abc"})

    assert created.name == "warehouse"
    assert created.kind == "databricks"
    assert created.endpoint == "https://example.cloud.databricks.com"
    assert created.token == "s3cr3t"
    assert created.credential_ref is None
    assert created.default_catalog == "main"
    assert created.options == {"warehouse_id": "abc"}

    events = created.collect_events()
    assert len(events) == 1
    assert isinstance(events[0], SourceConnection.Started)
    assert events[0].name == "warehouse"
    assert events[0].token == "s3cr3t"
    assert events[0].originator_id == created.id
    assert events[0].originator_version == 1


def test_event_classes_are_frozen_dataclasses() -> None:
    """Every connection event is an explicitly declared frozen dataclass."""
    for event_class in EVENT_CLASSES:
        assert is_dataclass(event_class), event_class.__qualname__
        assert event_class.__dataclass_params__.frozen, event_class.__qualname__


def test_events_cannot_be_mutated_after_creation() -> None:
    """Connection events are immutable."""
    event = connection().collect_events()[0]

    with pytest.raises(FrozenInstanceError):
        event.name = "other"  # type: ignore[misc]


def test_repr_never_leaks_the_inline_token() -> None:
    """The aggregate and its events redact the inline token."""
    created = connection()
    started = created.collect_events()[0]
    created.collect_events()

    created.rotate_credential(token="rotated")

    assert "s3cr3t" not in repr(created)
    assert "rotated" not in repr(created)
    assert "s3cr3t" not in repr(started)
    assert "rotated" not in repr(created.collect_events()[-1])


def test_a_connection_requires_exactly_one_credential() -> None:
    """Both or neither credential sources are rejected."""
    with pytest.raises(IngestionError, match="exactly one"):
        connection(credential_ref="env:DBX_TOKEN")

    with pytest.raises(IngestionError, match="exactly one"):
        connection(token=None)


def test_a_blank_inline_token_is_rejected() -> None:
    """An inline token that is only whitespace is rejected."""
    with pytest.raises(IngestionError, match="blank"):
        connection(token="   ")


def test_a_profile_connection_may_omit_the_endpoint() -> None:
    """A profile reference supplies the host, so an empty endpoint is allowed."""
    created = connection(token=None, credential_ref="profile:team", endpoint="")

    assert created.endpoint == ""
    assert created.credential_ref == "profile:team"


def test_an_empty_endpoint_needs_a_profile() -> None:
    """A connection without a profile still needs an endpoint."""
    with pytest.raises(IngestionError, match="endpoint is required"):
        connection(endpoint="   ")


def test_rotating_from_a_profile_to_a_token_needs_an_endpoint() -> None:
    """A token connection cannot keep the empty endpoint of a profile."""
    created = connection(token=None, credential_ref="profile:team", endpoint="")
    created.collect_events()

    with pytest.raises(IngestionError, match="endpoint is required"):
        created.rotate_credential(token="s3cr3t")


def test_change_updates_only_the_given_fields() -> None:
    """change() records one event and leaves the credential alone."""
    created = connection(default_catalog="main")
    created.collect_events()

    created.change(name="renamed", options={"warehouse_id": "xyz"})

    assert created.name == "renamed"
    assert created.endpoint == "https://example.cloud.databricks.com"
    assert created.default_catalog == "main"
    assert created.options == {"warehouse_id": "xyz"}
    assert created.token == "s3cr3t"
    event = created.collect_events()[-1]
    assert isinstance(event, SourceConnection.Changed)
    assert event.name == "renamed"
    assert event.endpoint is None
    assert event.originator_version == 2


def test_change_requires_at_least_one_field() -> None:
    """A no-op change is rejected before the aggregate mutates."""
    created = connection()
    created.collect_events()
    version = created.version

    with pytest.raises(ValueError, match="at least one"):
        created.change()

    assert created.version == version
    assert created.collect_events() == []


def test_rotate_credential_replaces_the_source() -> None:
    """Rotating switches from an inline token to an external reference."""
    created = connection()
    created.collect_events()

    created.rotate_credential(credential_ref="env:DBX_TOKEN")

    assert created.credential_ref == "env:DBX_TOKEN"
    assert created.token is None
    event = created.collect_events()[-1]
    assert isinstance(event, SourceConnection.CredentialRotated)
    assert event.credential_ref == "env:DBX_TOKEN"
    assert event.token is None


def test_rotate_credential_validates_its_input() -> None:
    """Rotation needs exactly one source and a non-blank inline token."""
    created = connection()
    created.collect_events()
    version = created.version

    with pytest.raises(IngestionError, match="exactly one"):
        created.rotate_credential(credential_ref="env:DBX_TOKEN", token="other")
    with pytest.raises(IngestionError, match="exactly one"):
        created.rotate_credential()
    with pytest.raises(IngestionError, match="blank"):
        created.rotate_credential(token=" ")

    assert created.version == version
    assert created.collect_events() == []


def test_discard_blocks_later_commands() -> None:
    """A discarded connection rejects every further command."""
    created = connection()
    created.collect_events()

    created.discard()

    assert created.version == 2
    with pytest.raises(DiscardedError):
        created.change(name="renamed")
    with pytest.raises(DiscardedError):
        created.rotate_credential(credential_ref="env:DBX_TOKEN")
    with pytest.raises(DiscardedError):
        created.discard()


def test_replay_restores_the_connection_state() -> None:
    """Applying the recorded events rebuilds the same aggregate state."""
    created = connection(credential_ref="env:DBX_TOKEN", token=None)
    created.change(name="renamed", default_catalog="main")
    created.rotate_credential(token="new-secret")
    created.discard()

    restored = replay(list(created.collect_events()))

    assert restored.id == created.id
    assert restored.name == "renamed"
    assert restored.default_catalog == "main"
    assert restored.token == "new-secret"
    assert restored.credential_ref is None
    assert restored.version == 4
