"""SourceConnection aggregate: a named external data source."""

from __future__ import annotations

from dataclasses import dataclass, field

from eventsourcing.domain import Aggregate, AggregateCreated, event

from etlalchemy.ingestion.aggregates.errors import DiscardedError, IngestionError
from etlalchemy.shared.credentials import profile_reference


def _validate_inline_secret(value: str | None) -> None:
    """Rejects an inline secret that is blank once stripped."""
    if value is not None and not value.strip():
        msg = "inline token must not be blank"
        raise IngestionError(msg)


def _validate_endpoint(endpoint: str, credential_ref: str | None) -> None:
    """Rejects a blank endpoint unless a local profile supplies the host."""
    if endpoint.strip() or profile_reference(credential_ref) is not None:
        return
    msg = "endpoint is required unless the connection uses a profile reference"
    raise IngestionError(msg)


class SourceConnection(Aggregate):
    """A user-created connection to an external data source.

    A connection stores only metadata and either an external
    ``credential_ref`` (``env:`` / ``file:`` / ``vault:`` ...) or an inline
    ``token``. When inline, the token lives inside the event state and is
    therefore encrypted at rest by the eventsourcing cipher when encryption is
    enabled. The read model never stores the token.
    """

    def __init__(
        self,
        name: str,
        kind: str,
        endpoint: str,
        credential_ref: str | None = None,
        token: str | None = None,
        default_catalog: str | None = None,
        options: dict[str, str] | None = None,
    ) -> None:
        """Initialises a connection with exactly one credential source."""
        if (credential_ref is None) == (token is None):
            msg = "exactly one of credential_ref / token is required"
            raise IngestionError(msg)
        _validate_inline_secret(token)
        _validate_endpoint(endpoint, credential_ref)
        self.name = name
        self.kind = kind
        self.endpoint = endpoint
        self.credential_ref = credential_ref
        self.token = token
        self.default_catalog = default_catalog
        self.options = {} if options is None else dict(options)
        self._is_discarded = False

    class Event(Aggregate.Event):
        """Base class for events raised by the SourceConnection aggregate."""

    @dataclass(frozen=True)
    class Started(AggregateCreated):
        """Recorded when a connection is created."""

        name: str
        """User-chosen name, unique across connections."""
        kind: str
        """Source kind, for example ``databricks``."""
        endpoint: str
        """Base URL or host of the source."""
        credential_ref: str | None = None
        """External secret reference, for example ``env:DBX_TOKEN``."""
        token: str | None = field(default=None, repr=False)
        """Inline secret, encrypted at rest by the eventsourcing cipher."""
        default_catalog: str | None = None
        """Catalog to use when an import does not name one."""
        options: dict[str, str] = field(default_factory=dict)
        """Kind-specific options, for example ``type_policy``."""

        def __repr__(self) -> str:
            """Renders the event without leaking the inline token."""
            return (
                f"SourceConnection.Started(name={self.name!r}, kind={self.kind!r}, "
                f"endpoint={self.endpoint!r}, credential_ref={self.credential_ref!r}, "
                f"token=<redacted>, default_catalog={self.default_catalog!r}, "
                f"options={self.options!r})"
            )

    @dataclass(frozen=True)
    class Changed(Event):
        """Recorded when connection metadata changes."""

        name: str | None = None
        """New name, or ``None`` when unchanged."""
        endpoint: str | None = None
        """New endpoint, or ``None`` when unchanged."""
        default_catalog: str | None = None
        """New default catalog, or ``None`` when unchanged."""
        options: dict[str, str] | None = None
        """New options, or ``None`` when unchanged."""

    @dataclass(frozen=True)
    class CredentialRotated(Event):
        """Recorded when the credential reference or inline token is replaced."""

        credential_ref: str | None = None
        """New external secret reference, or ``None`` when an inline token is used."""
        token: str | None = field(default=None, repr=False)
        """New inline secret, encrypted at rest by the eventsourcing cipher."""

        def __repr__(self) -> str:
            """Renders the event without leaking the inline token."""
            return (
                f"SourceConnection.CredentialRotated("
                f"credential_ref={self.credential_ref!r}, token=<redacted>)"
            )

    @dataclass(frozen=True)
    class Discarded(Event):
        """Recorded when the connection is discarded."""

    @event(Changed)
    def change(
        self,
        name: str | None = None,
        endpoint: str | None = None,
        default_catalog: str | None = None,
        options: dict[str, str] | None = None,
    ) -> None:
        """Changes connection metadata; the credential is not touched here."""
        self._ensure_not_discarded()
        if all(value is None for value in (name, endpoint, default_catalog, options)):
            msg = "change() requires at least one field"
            raise ValueError(msg)
        if name is not None:
            self.name = name
        if endpoint is not None:
            _validate_endpoint(endpoint, self.credential_ref)
            self.endpoint = endpoint
        if default_catalog is not None:
            self.default_catalog = default_catalog
        if options is not None:
            self.options = dict(options)

    @event(CredentialRotated)
    def rotate_credential(
        self,
        credential_ref: str | None = None,
        token: str | None = None,
    ) -> None:
        """Replaces the credential with exactly one new source."""
        self._ensure_not_discarded()
        if (credential_ref is None) == (token is None):
            msg = "exactly one of credential_ref / token is required"
            raise IngestionError(msg)
        _validate_inline_secret(token)
        _validate_endpoint(self.endpoint, credential_ref)
        self.credential_ref = credential_ref
        self.token = token

    @event(Discarded)
    def discard(self) -> None:
        """Marks the connection as discarded."""
        self._ensure_not_discarded()
        self._is_discarded = True

    def _ensure_not_discarded(self) -> None:
        """Raises DiscardedError when the connection has been discarded."""
        if self._is_discarded:
            msg = "connection is discarded"
            raise DiscardedError(msg)

    def __repr__(self) -> str:
        """Renders the aggregate without leaking the inline token."""
        return (
            f"SourceConnection(id={self.id}, name={self.name!r}, kind={self.kind!r}, "
            f"endpoint={self.endpoint!r}, credential_ref={self.credential_ref!r}, "
            f"token=<redacted>, default_catalog={self.default_catalog!r}, "
            f"options={self.options!r})"
        )
