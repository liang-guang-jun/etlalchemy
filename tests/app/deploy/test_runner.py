"""Tests for the deployment pipeline."""

from __future__ import annotations

import asyncio
from io import StringIO
from pathlib import Path

import pytest
from rich.console import Console

from etlalchemy.app.deploy.errors import AppNotFoundError, DeployError, DeploymentFailedError
from etlalchemy.app.deploy.models import DeployReport
from etlalchemy.app.deploy.runner import DeployOptions, run_deploy

from .support import FakeWorkspace, make_options, make_repo

WORKSPACE = "/Workspace/Users/user@example.com/etlalchemy"
"""Folder the tests synchronise to."""

MANIFEST = f"{WORKSPACE}/.etlalchemy-deploy.json"
"""Digest manifest the run writes."""

MANIFEST_TAIL = ".etlalchemy-deploy.json"
"""Suffix that identifies the manifest in the upload log."""


def console() -> Console:
    """Returns a console that writes to a buffer instead of a terminal."""
    return Console(file=StringIO(), force_terminal=False, width=120)


def run(options: DeployOptions, fake: FakeWorkspace) -> DeployReport:
    """Runs the pipeline against the fake workspace."""
    return asyncio.run(run_deploy(options, api=fake, console=console()))


def test_dry_run_plans_without_writing(tmp_path: Path) -> None:
    """``--dry-run`` reports the difference and stops."""
    root = make_repo(tmp_path / "repo")
    fake = FakeWorkspace()

    report = run(make_options(root, dry_run=True), fake)

    assert report.dry_run
    assert report.uploaded == 0
    assert report.plan.uploads
    assert fake.files == {}
    assert fake.deployments == []


def test_full_run_uploads_the_bundle_and_deploys(tmp_path: Path) -> None:
    """The staged package, the SPA and the app.yaml reach the app folder."""
    root = make_repo(tmp_path / "repo")
    fake = FakeWorkspace()

    report = run(make_options(root), fake)

    assert report.state == "SUCCEEDED"
    assert report.deployment_id == "deployment-1"
    assert report.url == "https://etlalchemy-123.cloud.databricksapps.com"
    assert report.uploaded == len(fake.uploads) - 1
    assert f"{WORKSPACE}/app.yaml" in fake.files
    assert f"{WORKSPACE}/dist/ui/index.html" in fake.files
    assert f"{WORKSPACE}/etlalchemy/__init__.py" in fake.files
    assert MANIFEST in fake.files
    assert fake.deployments == [("etlalchemy", WORKSPACE)]


def test_second_run_uploads_nothing(tmp_path: Path) -> None:
    """The manifest makes the next run a no-op."""
    root = make_repo(tmp_path / "repo")
    fake = FakeWorkspace()
    run(make_options(root), fake)
    uploads = len(fake.uploads)

    report = run(make_options(root), fake)

    assert report.plan.is_empty
    assert report.uploaded == 0
    assert len(fake.uploads) == uploads


def test_changed_file_is_uploaded_alone(tmp_path: Path) -> None:
    """Only the edited file travels, even when its size does not change."""
    root = make_repo(tmp_path / "repo")
    fake = FakeWorkspace()
    run(make_options(root), fake)
    bundle = root / "dist" / "ui" / "assets" / "index.js"
    bundle.write_text("console.log(2);", encoding="utf-8")
    uploads = len(fake.uploads)

    report = run(make_options(root), fake)

    assert [change.path for change in report.plan.uploads] == ["dist/ui/assets/index.js"]
    # The manifest travels with the change so the next run sees the new digest.
    written = [path for path in fake.uploads[uploads:] if not path.endswith(MANIFEST_TAIL)]
    assert written == [f"{WORKSPACE}/dist/ui/assets/index.js"]


def test_prune_removes_stale_files(tmp_path: Path) -> None:
    """``--prune`` deletes what the local tree no longer has."""
    root = make_repo(tmp_path / "repo")
    fake = FakeWorkspace()
    fake.files[f"{WORKSPACE}/stale.txt"] = b"old"

    report = run(make_options(root, prune=True), fake)

    assert report.removed == 1
    assert f"{WORKSPACE}/stale.txt" not in fake.files


def test_stale_files_stay_without_prune(tmp_path: Path) -> None:
    """Nothing is deleted by default."""
    root = make_repo(tmp_path / "repo")
    fake = FakeWorkspace()
    fake.files[f"{WORKSPACE}/stale.txt"] = b"old"

    report = run(make_options(root), fake)

    assert report.removed == 0
    assert f"{WORKSPACE}/stale.txt" in fake.files


def test_default_workspace_path_uses_the_profile_user(tmp_path: Path) -> None:
    """An unset folder resolves to the caller's home, which they can write to."""
    root = make_repo(tmp_path / "repo")

    report = run(make_options(root, workspace_path=""), FakeWorkspace())

    assert report.workspace_path == WORKSPACE


def test_unknown_app_fails_before_any_upload(tmp_path: Path) -> None:
    """A typo in the app name never creates a second app."""
    root = make_repo(tmp_path / "repo")
    fake = FakeWorkspace(app=None)

    with pytest.raises(AppNotFoundError):
        run(make_options(root), fake)

    assert fake.uploads == []


def test_non_interactive_run_requires_yes(tmp_path: Path) -> None:
    """An unattended shell must opt in explicitly."""
    root = make_repo(tmp_path / "repo")
    fake = FakeWorkspace()

    with pytest.raises(DeployError, match="non-interactive"):
        run(make_options(root, assume_yes=False), fake)

    assert fake.uploads == []


def test_failed_deployment_is_reported(tmp_path: Path) -> None:
    """A platform failure fails the command after the upload."""
    root = make_repo(tmp_path / "repo")
    fake = FakeWorkspace()
    fake.states = ["FAILED"]

    with pytest.raises(DeploymentFailedError, match="FAILED"):
        run(make_options(root), fake)


def test_missing_bundle_without_build_fails(tmp_path: Path) -> None:
    """``--no-build`` with an unbuilt frontend fails before staging."""
    root = make_repo(tmp_path / "repo")
    (root / "dist" / "ui" / "index.html").unlink()

    with pytest.raises(DeployError, match="frontend bundle is missing"):
        run(make_options(root, build=False), FakeWorkspace())
