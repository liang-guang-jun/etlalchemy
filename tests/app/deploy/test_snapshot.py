"""Tests for the local and remote snapshots and their comparison."""

from __future__ import annotations

import json
from pathlib import Path

from etlalchemy.app.deploy.models import FILE_OBJECT, ChangeKind, LocalFile, RemoteFile
from etlalchemy.app.deploy.snapshot import (
    MANIFEST_NAME,
    Manifest,
    local_snapshot,
    plan_changes,
    staging_directories,
)


def write(root: Path, name: str, content: str = "x") -> Path:
    """Writes a file below ``root`` and returns its path."""
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def local(path: str, content: str) -> LocalFile:
    """Builds a local snapshot entry with a stand-in digest."""
    return LocalFile(path=path, size=len(content), sha256=f"digest-{content}")


def remote(path: str, size: int, object_type: str = FILE_OBJECT) -> RemoteFile:
    """Builds a remote snapshot entry."""
    return RemoteFile(path=path, object_type=object_type, size=size)


def test_local_snapshot_digests_files_and_skips_generated_trees(tmp_path: Path) -> None:
    """Caches, virtual environments and VCS metadata never reach the workspace."""
    write(tmp_path, "etlalchemy/__init__.py", "x = 1\n")
    write(tmp_path, "etlalchemy/__pycache__/mod.cpython-313.pyc", "binary")
    write(tmp_path, "node_modules/pkg/index.js", "x")
    write(tmp_path, ".git/config", "x")
    write(tmp_path, "dist/ui/index.html", "<html></html>")

    snapshot = local_snapshot(tmp_path)

    assert sorted(snapshot) == ["dist/ui/index.html", "etlalchemy/__init__.py"]
    assert snapshot["etlalchemy/__init__.py"].size == len("x = 1\n")
    assert len(snapshot["etlalchemy/__init__.py"].sha256) == 64


def test_local_snapshot_honours_extra_excludes(tmp_path: Path) -> None:
    """Callers can leave individual files out."""
    write(tmp_path, "keep.txt")
    write(tmp_path, "skip.txt")

    assert sorted(local_snapshot(tmp_path, exclude=["skip.txt"])) == ["keep.txt"]


def test_staging_directories_lists_parents_first() -> None:
    """``mkdirs`` receives a tree it can create top down."""
    files = {
        "dist/ui/assets/index.js": local("dist/ui/assets/index.js", "x"),
        "etlalchemy/app/api/app.py": local("etlalchemy/app/api/app.py", "x"),
        "app.yaml": local("app.yaml", "x"),
    }

    assert staging_directories(files) == [
        "dist",
        "etlalchemy",
        "dist/ui",
        "etlalchemy/app",
        "dist/ui/assets",
        "etlalchemy/app/api",
    ]


def test_manifest_round_trips_through_bytes() -> None:
    """The next run reads back exactly the digests the upload recorded."""
    files = {
        "app.yaml": local("app.yaml", "a"),
        "dist/ui/index.html": local("dist/ui/index.html", "b"),
    }

    restored = Manifest.parse(Manifest.from_snapshot(files).to_bytes(app_name="etlalchemy"))

    assert restored.files == {path: entry.sha256 for path, entry in files.items()}


def test_manifest_tolerates_unusable_content() -> None:
    """A hand-edited or truncated manifest degrades to the size comparison."""
    assert Manifest.parse(b"not json").files == {}
    assert Manifest.parse(json.dumps({"files": []}).encode()).files == {}
    assert Manifest.parse(b'{"files": {"a": {"sha256": "x"}, "b": 1}}').files == {"a": "x"}


def test_plan_classifies_every_file() -> None:
    """Added, updated and unchanged files are told apart by digest."""
    local_files = {
        "app.yaml": local("app.yaml", "a"),
        "new.txt": local("new.txt", "n"),
        "same.txt": local("same.txt", "s"),
        "changed.txt": local("changed.txt", "c2"),
    }
    remote_files = {
        "app.yaml": remote("app.yaml", 1),
        "same.txt": remote("same.txt", 1),
        "changed.txt": remote("changed.txt", 2),
    }
    manifest = Manifest(
        files={"app.yaml": "digest-a", "same.txt": "digest-s", "changed.txt": "digest-c1"},
    )

    plan = plan_changes(local_files, remote_files, manifest)

    kinds = {change.path: change.kind for change in plan.changes}
    assert kinds == {
        "app.yaml": ChangeKind.UNCHANGED,
        "changed.txt": ChangeKind.UPDATED,
        "new.txt": ChangeKind.ADDED,
        "same.txt": ChangeKind.UNCHANGED,
    }
    assert [change.path for change in plan.uploads] == ["changed.txt", "new.txt"]
    assert plan.bytes_to_upload == 2 + 1


def test_plan_falls_back_to_size_without_a_manifest() -> None:
    """A folder that predates the manifest compares sizes only."""
    local_files = {"a.txt": local("a.txt", "aa"), "b.txt": local("b.txt", "bb")}
    remote_files = {"a.txt": remote("a.txt", 2), "b.txt": remote("b.txt", 5)}

    plan = plan_changes(local_files, remote_files, Manifest.empty())

    kinds = {change.path: change.kind for change in plan.changes}
    assert kinds == {"a.txt": ChangeKind.UNCHANGED, "b.txt": ChangeKind.UPDATED}


def test_plan_replaces_a_directory_and_never_removes_the_manifest() -> None:
    """A directory in the file's place is an update, and the manifest stays."""
    local_files = {"a.txt": local("a.txt", "aa")}
    remote_files = {
        "a.txt": remote("a.txt", 0, object_type="DIRECTORY"),
        "stale.txt": remote("stale.txt", 1),
        MANIFEST_NAME: remote(MANIFEST_NAME, 1),
    }

    plan = plan_changes(local_files, remote_files, Manifest.empty())

    assert [change.kind for change in plan.changes] == [ChangeKind.UPDATED]
    assert plan.removals == ("stale.txt",)


def test_force_uploads_every_file() -> None:
    """``--force`` ignores the recorded digests."""
    local_files = {"a.txt": local("a.txt", "aa")}
    manifest = Manifest(files={"a.txt": "digest-aa"})

    plan = plan_changes(local_files, {"a.txt": remote("a.txt", 2)}, manifest, force=True)

    assert [change.kind for change in plan.changes] == [ChangeKind.UPDATED]


def test_empty_plan_reports_no_work() -> None:
    """Identical trees produce an empty plan."""
    local_files = {"a.txt": local("a.txt", "aa")}
    manifest = Manifest(files={"a.txt": "digest-aa"})

    plan = plan_changes(local_files, {"a.txt": remote("a.txt", 2)}, manifest)

    assert plan.is_empty
    assert plan.bytes_to_upload == 0
