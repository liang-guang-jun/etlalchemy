"""Term aggregate: owns the definition, aliases and catalog links of a term."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from eventsourcing.domain import Aggregate, AggregateCreated, event

from etlalchemy.vocabulary.aggregates.errors import (
    DiscardedError,
    DuplicateAliasError,
    InvalidAliasError,
    InvalidLinkError,
    InvalidPathError,
    InvalidTermNameError,
    InvalidTermStateError,
    UnknownAliasError,
    UnknownLinkError,
)
from etlalchemy.vocabulary.aggregates.types import (
    TARGET_KINDS,
    TermLink,
    TermStatus,
    normalise_color,
)


def _validate_name(name: str) -> None:
    """Rejects a term name that cannot be used as one path segment."""
    if not name.strip():
        msg = "term name must not be blank"
        raise InvalidTermNameError(msg)
    if "/" in name:
        msg = "term name must not contain '/'"
        raise InvalidTermNameError(msg)


def _validate_path_for_name(path: str, name: str) -> None:
    """Rejects a path that is blank or does not end with the term name."""
    if not path or path != path.strip():
        msg = "term path must be a non-blank path"
        raise InvalidPathError(msg)
    if path != name and not path.endswith(f"/{name}"):
        msg = f"term path {path!r} does not end with {name!r}"
        raise InvalidPathError(msg)


class Term(Aggregate):
    """Aggregate root for a term in the domain tree.

    A term starts as a ``draft``. ``approve`` freezes its content, ``reopen`` and
    ``reactivate`` bring it back to ``draft``, so every content change is an
    explicit, auditable state transition. ``path`` is aggregate state because it
    is the uniqueness key of the domain registry. ``color`` is presentation
    metadata, so it stays editable in every live status.
    """

    def __init__(
        self,
        domain_id: UUID,
        name: str,
        definition: str,
        aliases: tuple[str, ...] = (),
        parent_id: UUID | None = None,
        path: str = "",
        color: str = "",
    ) -> None:
        """Initialises a draft term in the given domain and tree position."""
        _validate_name(name)
        initial_path = path or name
        _validate_path_for_name(initial_path, name)
        self.domain_id = domain_id
        self.name = name
        self.definition = definition
        self.aliases: dict[str, None] = dict.fromkeys(aliases)
        self.parent_id = parent_id
        self.path = initial_path
        self.status = TermStatus.DRAFT
        self.color = normalise_color(color)
        self.links: dict[TermLink, None] = {}
        self._is_discarded = False

    class Event(Aggregate.Event):
        """Base class for events raised by the term aggregate."""

    @dataclass(frozen=True)
    class Started(AggregateCreated):
        """Recorded when a term is created."""

        domain_id: UUID
        """ID of the domain that owns the term."""
        name: str
        """Name of the new term."""
        definition: str
        """Initial definition of the new term."""
        aliases: tuple[str, ...] = ()
        """Initial aliases of the new term."""
        parent_id: UUID | None = None
        """ID of the parent term, or ``None`` for a top-level term."""
        path: str = ""
        """Path of the new term inside its domain."""
        color: str = ""
        """Initial colour of the new term as ``#rrggbb``, or empty for none."""

    @dataclass(frozen=True)
    class ColorChanged(Event):
        """Recorded when the presentation colour of the term changes."""

        color: str
        """Colour after the change as ``#rrggbb``, or empty for none."""

    @dataclass(frozen=True)
    class DefinitionChanged(Event):
        """Recorded when the term definition changes."""

        definition: str
        """Definition after the change."""

    @dataclass(frozen=True)
    class AliasAdded(Event):
        """Recorded when an alias is added to the term."""

        alias: str
        """Alias that was added."""

    @dataclass(frozen=True)
    class AliasRemoved(Event):
        """Recorded when an alias is removed from the term."""

        alias: str
        """Alias that was removed."""

    @dataclass(frozen=True)
    class Approved(Event):
        """Recorded when a draft term is approved."""

        reviewer: str | None = None
        """Optional name of the reviewer."""

    @dataclass(frozen=True)
    class Reopened(Event):
        """Recorded when an approved term is reopened for editing."""

        reason: str | None = None
        """Optional reason for reopening the term."""

    @dataclass(frozen=True)
    class Deprecated(Event):
        """Recorded when an approved term is deprecated."""

        reason: str | None = None
        """Optional reason for deprecating the term."""

    @dataclass(frozen=True)
    class Reactivated(Event):
        """Recorded when a deprecated term is reactivated for editing."""

        reason: str | None = None
        """Optional reason for reactivating the term."""

    @dataclass(frozen=True)
    class Linked(Event):
        """Recorded when the term is linked to a catalog object."""

        target_id: UUID
        """ID of the linked catalog, schema, table or owning table."""
        target_kind: str
        """Kind of the linked object."""
        field_name: str = ""
        """Field name for ``field`` links, empty otherwise."""

    @dataclass(frozen=True)
    class Unlinked(Event):
        """Recorded when a catalog link is removed from the term."""

        target_id: UUID
        """ID of the linked catalog, schema, table or owning table."""
        target_kind: str
        """Kind of the linked object."""
        field_name: str = ""
        """Field name for ``field`` links, empty otherwise."""

    @dataclass(frozen=True)
    class Renamed(Event):
        """Recorded when the term name and path change."""

        new_name: str
        """New name of the term."""
        new_path: str
        """New path of the term."""

    @dataclass(frozen=True)
    class Moved(Event):
        """Recorded when the term moves under another parent."""

        parent_id: UUID | None = None
        """ID of the new parent term, or ``None`` for the top level."""
        new_path: str = ""
        """New path of the term."""

    @dataclass(frozen=True)
    class Repathed(Event):
        """Recorded when only the path changes, for example after an ancestor rename."""

        new_path: str
        """New path of the term."""

    @dataclass(frozen=True)
    class Discarded(Event):
        """Recorded when the term is discarded."""

    # -- content edits (draft only) ----------------------------------------

    @event(DefinitionChanged)
    def change_definition(self, definition: str) -> None:
        """Replaces the term definition."""
        self._ensure_editable()
        self.definition = definition

    def change_color(self, color: str) -> None:
        """Sets the presentation colour of the term.

        Colour is metadata rather than content, so it stays editable after the
        term was approved or deprecated; only discarded terms reject it.
        """
        self._ensure_not_discarded()
        normalised = normalise_color(color)
        if self.color == normalised:
            return
        self._color_changed(normalised)

    @event(ColorChanged)
    def _color_changed(self, color: str) -> None:
        """Records the new colour of the term."""
        self.color = color

    @event(AliasAdded)
    def add_alias(self, alias: str) -> None:
        """Adds an alias to the term."""
        self._ensure_editable()
        if not alias:
            msg = "alias must not be blank"
            raise InvalidAliasError(msg)
        if alias in self.aliases:
            msg = f"Alias {alias!r} already exists on term {self.name!r}"
            raise DuplicateAliasError(msg)
        self.aliases[alias] = None

    @event(AliasRemoved)
    def remove_alias(self, alias: str) -> None:
        """Removes an alias from the term."""
        self._ensure_editable()
        if alias not in self.aliases:
            msg = f"Alias {alias!r} does not exist on term {self.name!r}"
            raise UnknownAliasError(msg)
        del self.aliases[alias]

    def link(self, target_id: UUID, target_kind: str, field_name: str = "") -> None:
        """Links the term to a catalog object; linking twice is a no-op."""
        self._ensure_editable()
        self._validate_link(target_id, target_kind, field_name)
        if TermLink(target_id, target_kind, field_name) in self.links:
            return
        self._link(target_id, target_kind, field_name)

    @event(Linked)
    def _link(self, target_id: UUID, target_kind: str, field_name: str = "") -> None:
        """Records the new link in the term."""
        self.links[TermLink(target_id, target_kind, field_name)] = None

    def unlink(self, target_id: UUID, target_kind: str, field_name: str = "") -> None:
        """Removes a catalog link from the term."""
        self._ensure_editable()
        link = TermLink(target_id, target_kind, field_name)
        if link not in self.links:
            msg = f"Term {self.name!r} is not linked to {link.target_kind} {link.target_id}"
            raise UnknownLinkError(msg)
        self._unlink(target_id, target_kind, field_name)

    @event(Unlinked)
    def _unlink(self, target_id: UUID, target_kind: str, field_name: str = "") -> None:
        """Records the removal of the link from the term."""
        del self.links[TermLink(target_id, target_kind, field_name)]

    # -- state transitions --------------------------------------------------

    @event(Approved)
    def approve(self, reviewer: str | None = None) -> None:
        """Approves a draft term."""
        self._ensure_status(TermStatus.DRAFT, "approve")
        self.status = TermStatus.APPROVED

    @event(Reopened)
    def reopen(self, reason: str | None = None) -> None:
        """Reopens an approved term for editing."""
        self._ensure_status(TermStatus.APPROVED, "reopen")
        self.status = TermStatus.DRAFT

    @event(Deprecated)
    def deprecate(self, reason: str | None = None) -> None:
        """Deprecates an approved term."""
        self._ensure_status(TermStatus.APPROVED, "deprecate")
        self.status = TermStatus.DEPRECATED

    @event(Reactivated)
    def reactivate(self, reason: str | None = None) -> None:
        """Reactivates a deprecated term for editing."""
        self._ensure_status(TermStatus.DEPRECATED, "reactivate")
        self.status = TermStatus.DRAFT

    # -- name, position and lifetime ---------------------------------------

    def rename(self, new_name: str, new_path: str) -> None:
        """Renames a term that is a draft or approved.

        The path must be the parent path plus the new name. Validation runs
        before the event is recorded, so a rejected rename leaves the term
        unchanged.
        """
        self._ensure_renamable()
        _validate_name(new_name)
        parent_path = self.path.rpartition("/")[0]
        expected = f"{parent_path}/{new_name}" if parent_path else new_name
        if new_path != expected:
            msg = f"rename path {new_path!r} does not match {expected!r}"
            raise InvalidPathError(msg)
        if self.name == new_name and self.path == new_path:
            return
        self._renamed(new_name, new_path)

    @event(Renamed)
    def _renamed(self, new_name: str, new_path: str) -> None:
        """Records the new name and path of the term."""
        self.name = new_name
        self.path = new_path

    def move(self, parent_id: UUID | None, new_path: str) -> None:
        """Moves a draft or approved term under another parent.

        The aggregate can only check that the path ends with the term name; the
        application owns the parent path prefix.
        """
        self._ensure_movable()
        _validate_path_for_name(new_path, self.name)
        if parent_id == self.parent_id and new_path == self.path:
            return
        self._moved(parent_id, new_path)

    @event(Moved)
    def _moved(self, parent_id: UUID | None = None, new_path: str = "") -> None:
        """Records the new parent and path of the term."""
        self.parent_id = parent_id
        self.path = new_path

    def repath(self, new_path: str) -> None:
        """Changes only the path, as required when an ancestor is renamed or moved."""
        self._ensure_not_discarded()
        _validate_path_for_name(new_path, self.name)
        if self.path == new_path:
            return
        self._repathed(new_path)

    @event(Repathed)
    def _repathed(self, new_path: str) -> None:
        """Records the new path of the term."""
        self.path = new_path

    @event(Discarded)
    def discard(self) -> None:
        """Marks the term as discarded."""
        self._ensure_not_discarded()
        self._is_discarded = True

    # -- guards -------------------------------------------------------------

    def _ensure_editable(self) -> None:
        """Raises InvalidTermStateError unless the term is a draft."""
        self._ensure_not_discarded()
        if self.status != TermStatus.DRAFT:
            msg = f"term is {self.status}; reopen or reactivate it before editing"
            raise InvalidTermStateError(msg)

    def _ensure_renamable(self) -> None:
        """Raises InvalidTermStateError unless the term is a draft or approved."""
        self._ensure_not_discarded()
        if self.status not in (TermStatus.DRAFT, TermStatus.APPROVED):
            msg = f"cannot rename a term in status {self.status}"
            raise InvalidTermStateError(msg)

    def _ensure_movable(self) -> None:
        """Raises InvalidTermStateError unless the term is a draft or approved."""
        self._ensure_not_discarded()
        if self.status not in (TermStatus.DRAFT, TermStatus.APPROVED):
            msg = f"cannot move a term in status {self.status}"
            raise InvalidTermStateError(msg)

    def _ensure_status(self, expected: TermStatus, action: str) -> None:
        """Raises InvalidTermStateError unless the term has the expected status."""
        self._ensure_not_discarded()
        if self.status != expected:
            msg = f"cannot {action} a term in status {self.status}"
            raise InvalidTermStateError(msg)

    def _ensure_not_discarded(self) -> None:
        """Raises DiscardedError when the term has been discarded."""
        if self._is_discarded:
            msg = "term is discarded"
            raise DiscardedError(msg)

    @staticmethod
    def _validate_link(target_id: UUID, target_kind: str, field_name: str) -> None:
        """Rejects a link whose kind or field name is inconsistent."""
        if target_kind not in TARGET_KINDS:
            msg = f"unknown target_kind: {target_kind!r}"
            raise InvalidLinkError(msg)
        if target_kind == "field":
            if not field_name:
                msg = "field link requires a field_name"
                raise InvalidLinkError(msg)
        elif field_name:
            msg = f"{target_kind} link must not carry a field_name"
            raise InvalidLinkError(msg)
