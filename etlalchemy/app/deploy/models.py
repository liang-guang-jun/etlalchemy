"""Value objects of the deployment: snapshots, change classes and the report."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

FILE_OBJECT = "FILE"
"""Object type the workspace API reports for a file."""

DIRECTORY_OBJECT = "DIRECTORY"
"""Object type the workspace API reports for a folder."""


class ChangeKind(StrEnum):
    """How one local file relates to the remote copy."""

    ADDED = "added"
    """The file does not exist remotely."""

    UPDATED = "updated"
    """The file exists remotely with different content."""

    UNCHANGED = "unchanged"
    """The remote copy already matches the local one."""


@dataclass(frozen=True, slots=True)
class LocalFile:
    """One file of the staged source tree."""

    path: str
    """Path relative to the app root, using forward slashes."""

    size: int
    """Size in bytes."""

    sha256: str
    """Hex digest of the content, used for the incremental comparison."""


@dataclass(frozen=True, slots=True)
class RemoteFile:
    """One object of the remote workspace tree."""

    path: str
    """Path relative to the app root, using forward slashes."""

    object_type: str
    """Workspace object type, normally ``FILE`` or ``DIRECTORY``."""

    size: int | None = None
    """Size in bytes, only reported for files."""


@dataclass(frozen=True, slots=True)
class FileChange:
    """One classified local file."""

    path: str
    """Path relative to the app root."""

    kind: ChangeKind
    """The classification."""

    size: int
    """Size in bytes."""


@dataclass(frozen=True, slots=True)
class DeployPlan:
    """The difference between the local bundle and the remote folder."""

    changes: tuple[FileChange, ...]
    """Every local file, sorted by path."""

    removals: tuple[str, ...]
    """Remote files that no longer exist locally, sorted by path."""

    @property
    def uploads(self) -> tuple[FileChange, ...]:
        """Returns the files that have to be written."""
        return tuple(change for change in self.changes if change.kind is not ChangeKind.UNCHANGED)

    @property
    def added(self) -> tuple[FileChange, ...]:
        """Returns the files that only exist locally."""
        return tuple(change for change in self.changes if change.kind is ChangeKind.ADDED)

    @property
    def updated(self) -> tuple[FileChange, ...]:
        """Returns the files that exist on both sides with different content."""
        return tuple(change for change in self.changes if change.kind is ChangeKind.UPDATED)

    @property
    def unchanged(self) -> tuple[FileChange, ...]:
        """Returns the files that need no upload."""
        return tuple(change for change in self.changes if change.kind is ChangeKind.UNCHANGED)

    @property
    def bytes_to_upload(self) -> int:
        """Returns the number of bytes the uploads move."""
        return sum(change.size for change in self.uploads)

    @property
    def is_empty(self) -> bool:
        """Returns whether the remote folder already matches the local one."""
        return not self.uploads and not self.removals


@dataclass(frozen=True, slots=True)
class DeployReport:
    """Outcome of one deployment run."""

    profile: str
    """Profile the run authenticated with."""

    host: str
    """Workspace host, for the JSON output."""

    app_name: str
    """Target app."""

    workspace_path: str
    """Folder the source was synchronised to."""

    plan: DeployPlan
    """The difference the run computed."""

    uploaded: int
    """Number of files written."""

    removed: int
    """Number of files deleted."""

    bytes_uploaded: int
    """Number of bytes written."""

    dry_run: bool
    """Whether the run stopped after planning."""

    deployment_id: str | None = None
    """Deployment the platform created."""

    state: str | None = None
    """Final deployment state, for example ``SUCCEEDED``."""

    url: str | None = None
    """URL of the running app, when the platform reports one."""

    warnings: tuple[str, ...] = ()
    """Preflight warnings the operator should read."""

    def to_json(self) -> dict[str, Any]:
        """Returns the report as a JSON-serialisable mapping.

        Returns:
            A flat mapping the CLI can print with ``--json``.
        """
        return {
            "profile": self.profile,
            "host": self.host,
            "app_name": self.app_name,
            "workspace_path": self.workspace_path,
            "dry_run": self.dry_run,
            "uploaded": self.uploaded,
            "removed": self.removed,
            "bytes_uploaded": self.bytes_uploaded,
            "added": [change.path for change in self.plan.added],
            "updated": [change.path for change in self.plan.updated],
            "unchanged": len(self.plan.unchanged),
            "removals": list(self.plan.removals),
            "deployment_id": self.deployment_id,
            "state": self.state,
            "url": self.url,
            "warnings": list(self.warnings),
        }
