"""Domain aggregate: registers the term tree of one business domain."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from eventsourcing.domain import Aggregate, AggregateCreated, event

from etlalchemy.vocabulary.aggregates.errors import (
    DiscardedError,
    DuplicateTermError,
    UnknownTermError,
)


class Domain(Aggregate):
    """Aggregate root that registers the terms of one business domain.

    Terms are separate aggregates in a tree, so this aggregate only keeps the
    mapping from term path to term id. The path is the uniqueness key: the
    registry rejects a duplicate path before any term is saved.

    ``_paths`` mirrors ``terms`` by id so lookups and cascades are O(1) per term.
    It is derived state: replaying the same events rebuilds both mappings.
    """

    def __init__(self, name: str, description: str = "") -> None:
        """Initialises a domain with the given name and description."""
        self.name = name
        self.description = description
        self.terms: dict[str, UUID] = {}
        self._paths: dict[UUID, str] = {}
        self._is_discarded = False

    class Event(Aggregate.Event):
        """Base class for events raised by the domain aggregate."""

    @dataclass(frozen=True)
    class Started(AggregateCreated):
        """Recorded when a domain is created."""

        name: str
        """Name of the new domain."""
        description: str = ""
        """Free-form description of the new domain."""

    @dataclass(frozen=True)
    class TermRegistered(Event):
        """Recorded when a term is registered under a path."""

        term_path: str
        """Path the term is registered under."""
        term_id: UUID
        """ID of the term aggregate."""

    @dataclass(frozen=True)
    class TermUnregistered(Event):
        """Recorded when a term path is unregistered."""

        term_path: str
        """Path the term was registered under."""

    @dataclass(frozen=True)
    class TermRepathed(Event):
        """Recorded when a registered term moves to a new path."""

        term_id: UUID
        """ID of the repathed term aggregate."""
        new_path: str
        """New path the term is registered under."""

    @dataclass(frozen=True)
    class Changed(Event):
        """Recorded when the domain name or description changes."""

        name: str | None = None
        """New name, or ``None`` when unchanged."""
        description: str | None = None
        """New description, or ``None`` when unchanged."""

    @dataclass(frozen=True)
    class Discarded(Event):
        """Recorded when the domain is discarded."""

    @event(TermRegistered)
    def register_term(self, term_path: str, term_id: UUID) -> None:
        """Registers a term aggregate under the given path."""
        self._ensure_not_discarded()
        if term_path in self.terms:
            msg = f"Term path {term_path!r} already exists in domain {self.name!r}"
            raise DuplicateTermError(msg)
        self.terms[term_path] = term_id
        self._paths[term_id] = term_path

    @event(TermUnregistered)
    def unregister_term(self, term_path: str) -> None:
        """Unregisters the term with the given path."""
        self._ensure_not_discarded()
        term_id = self.term_id(term_path)
        del self.terms[term_path]
        del self._paths[term_id]

    @event(TermRepathed)
    def repath_term(self, term_id: UUID, new_path: str) -> None:
        """Replaces the path a registered term is known under."""
        self._ensure_not_discarded()
        old_path = self._registered_path(term_id)
        existing_id = self.terms.get(new_path)
        if existing_id is not None and existing_id != term_id:
            msg = f"Term path {new_path!r} already exists in domain {self.name!r}"
            raise DuplicateTermError(msg)
        if old_path != new_path:
            del self.terms[old_path]
        self.terms[new_path] = term_id
        self._paths[term_id] = new_path

    @event(Changed)
    def change(self, name: str | None = None, description: str | None = None) -> None:
        """Changes the domain name and/or description."""
        self._ensure_not_discarded()
        if name is None and description is None:
            msg = "change() requires a new name or description"
            raise ValueError(msg)
        if name is not None:
            self.name = name
        if description is not None:
            self.description = description

    @event(Discarded)
    def discard(self) -> None:
        """Marks the domain as discarded."""
        self._ensure_not_discarded()
        self._is_discarded = True

    def term_id(self, term_path: str) -> UUID:
        """Returns the id of the term registered under the given path."""
        try:
            return self.terms[term_path]
        except KeyError:
            msg = f"Term path {term_path!r} does not exist in domain {self.name!r}"
            raise UnknownTermError(msg) from None

    def has_term(self, term_id: UUID) -> bool:
        """Returns whether the term id is registered in this domain."""
        return term_id in self._paths

    def _registered_path(self, term_id: UUID) -> str:
        """Returns the path a term is registered under."""
        try:
            return self._paths[term_id]
        except KeyError:
            msg = f"Term {term_id} is not registered in domain {self.name!r}"
            raise UnknownTermError(msg) from None

    def _ensure_not_discarded(self) -> None:
        """Raises DiscardedError when the domain has been discarded."""
        if self._is_discarded:
            msg = "domain is discarded"
            raise DiscardedError(msg)
