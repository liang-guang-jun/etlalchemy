"""Snapshots of the local bundle and the remote workspace folder.

The Workspace listing reports a size but no content hash, so a same-size edit is
invisible to a listing alone. The deployment therefore records the digest of
every uploaded file in a small manifest inside the app folder, which makes the
next comparison exact and costs one extra file per run. A folder that predates
the manifest falls back to the reported size.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from etlalchemy.app.deploy.models import (
    FILE_OBJECT,
    ChangeKind,
    DeployPlan,
    FileChange,
    LocalFile,
    RemoteFile,
)

MANIFEST_NAME = ".etlalchemy-deploy.json"
"""Name of the digest manifest written into the app folder."""

MANIFEST_VERSION = 1
"""Schema version of the manifest."""

EXCLUDED_DIRECTORIES = frozenset(
    {
        ".cache",
        ".git",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".venv",
        "__pycache__",
        "node_modules",
    },
)
"""Directories that are never part of the app source."""

EXCLUDED_SUFFIXES = (".pyc", ".pyo", ".DS_Store")
"""File suffixes that are never part of the app source."""

READ_CHUNK_BYTES = 1 << 20
"""Read size of the digest loop, so a large bundle does not sit in memory twice."""


def local_snapshot(root: Path, *, exclude: Iterable[str] = ()) -> dict[str, LocalFile]:
    """Digests every file of the staged bundle.

    Args:
        root: Directory holding the app source.
        exclude: Extra paths, relative to ``root``, to leave out.

    Returns:
        One entry per file, keyed by its forward-slash relative path and sorted
        by that path.
    """
    skipped = {Path(item).as_posix().strip("/") for item in exclude}
    files: dict[str, LocalFile] = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        if relative in skipped or _is_excluded(relative):
            continue
        size, digest = file_digest(path)
        files[relative] = LocalFile(path=relative, size=size, sha256=digest)
    return files


def file_digest(path: Path) -> tuple[int, str]:
    """Returns the size and SHA-256 digest of a file.

    Args:
        path: File to read.

    Returns:
        The size in bytes and the hexadecimal digest.
    """
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(READ_CHUNK_BYTES), b""):
            digest.update(chunk)
            size += len(chunk)
    return size, digest.hexdigest()


def staging_directories(files: Mapping[str, LocalFile]) -> list[str]:
    """Returns every directory the files need, parents before children.

    Args:
        files: Snapshot of the staged bundle.

    Returns:
        The relative directory paths, shortest first, so ``mkdirs`` only ever
        creates a tree the API can walk.
    """
    directories: set[str] = set()
    for path in files:
        parent = Path(path).parent
        while parent.as_posix() not in ("", "."):
            directories.add(parent.as_posix())
            parent = parent.parent
    return sorted(directories, key=lambda item: (item.count("/"), item))


@dataclass(frozen=True, slots=True)
class Manifest:
    """Digests of the files the previous run uploaded."""

    files: Mapping[str, str]
    """Relative path to the SHA-256 hex digest written by the previous run."""

    @classmethod
    def empty(cls) -> Manifest:
        """Returns a manifest for a folder that has never been deployed.

        Returns:
            A manifest without entries.
        """
        return cls(files={})

    @classmethod
    def parse(cls, raw: bytes) -> Manifest:
        """Reads a manifest, tolerating a missing or hand-edited file.

        Args:
            raw: Content of ``.etlalchemy-deploy.json``.

        Returns:
            The parsed manifest, or an empty one when the content is unusable.
        """
        try:
            data: Any = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return cls.empty()
        entries = data.get("files") if isinstance(data, dict) else None
        if not isinstance(entries, dict):
            return cls.empty()
        files = {
            str(path): str(entry.get("sha256", ""))
            for path, entry in entries.items()
            if isinstance(path, str) and isinstance(entry, dict) and entry.get("sha256")
        }
        return cls(files=files)

    def to_bytes(self, *, app_name: str) -> bytes:
        """Serialises the manifest for the next run.

        Args:
            app_name: App the manifest belongs to, recorded for support cases.

        Returns:
            The UTF-8 encoded JSON document.
        """
        document = {
            "version": MANIFEST_VERSION,
            "app": app_name,
            "generated_at": datetime.now(tz=UTC).isoformat(),
            "files": {path: {"sha256": digest} for path, digest in sorted(self.files.items())},
        }
        return json.dumps(document, indent=2, sort_keys=False).encode("utf-8")

    @classmethod
    def from_snapshot(cls, files: Mapping[str, LocalFile]) -> Manifest:
        """Builds the manifest a successful upload leaves behind.

        Args:
            files: Snapshot that was uploaded.

        Returns:
            A manifest holding the digest of every file.
        """
        return cls(files={path: entry.sha256 for path, entry in files.items()})


def plan_changes(
    local: Mapping[str, LocalFile],
    remote: Mapping[str, RemoteFile],
    manifest: Manifest,
    *,
    force: bool = False,
) -> DeployPlan:
    """Classifies every local file against the remote folder.

    Args:
        local: Snapshot of the staged bundle.
        remote: Remote tree, keyed by the path relative to the app folder.
        manifest: Digests recorded by the previous run.
        force: Upload every file even when the digests match.

    Returns:
        The plan, with the remote files that no longer exist locally listed as
        removals (the caller decides whether to prune them).
    """
    changes: list[FileChange] = []
    for path in sorted(local):
        entry = local[path]
        current = remote.get(path)
        if force or current is None:
            kind = ChangeKind.ADDED if current is None else ChangeKind.UPDATED
        elif current.object_type != FILE_OBJECT:
            # A directory (or a notebook) sits where a file belongs: replace it.
            kind = ChangeKind.UPDATED
        elif _matches(entry, current, manifest):
            kind = ChangeKind.UNCHANGED
        else:
            kind = ChangeKind.UPDATED
        changes.append(FileChange(path=path, kind=kind, size=entry.size))
    removals = tuple(
        sorted(
            path
            for path, entry in remote.items()
            if path != MANIFEST_NAME and path not in local and entry.object_type == FILE_OBJECT
        ),
    )
    return DeployPlan(changes=tuple(changes), removals=removals)


def _matches(entry: LocalFile, current: RemoteFile, manifest: Manifest) -> bool:
    """Returns whether the remote copy already holds the local content.

    Args:
        entry: Local file.
        current: Remote object at the same path.
        manifest: Digests recorded by the previous run.

    Returns:
        ``True`` when the recorded digest matches, or, for a folder without a
        manifest, when the size matches.
    """
    recorded = manifest.files.get(entry.path)
    if recorded is not None:
        return recorded == entry.sha256
    return current.size is not None and current.size == entry.size


def _is_excluded(relative: str) -> bool:
    """Returns whether a relative path belongs to a generated or vendored tree.

    Args:
        relative: Forward-slash path relative to the bundle root.

    Returns:
        ``True`` for byte-code caches, virtual environments and VCS metadata.
    """
    if relative.endswith(EXCLUDED_SUFFIXES):
        return True
    return any(part in EXCLUDED_DIRECTORIES for part in Path(relative).parts)
