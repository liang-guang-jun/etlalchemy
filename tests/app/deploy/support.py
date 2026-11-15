"""Helpers shared by the deployment tests."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from etlalchemy.app.deploy.errors import AppNotFoundError
from etlalchemy.app.deploy.models import DIRECTORY_OBJECT, FILE_OBJECT, RemoteFile
from etlalchemy.app.deploy.runner import DeployOptions

APP: dict[str, Any] = {"name": "etlalchemy", "url": "etlalchemy-123.cloud.databricksapps.com"}
"""App object the fake workspace returns."""


def make_repo(root: Path, *, backend: str = "postgres") -> Path:
    """Writes a miniature repository the staging step accepts.

    Args:
        root: Directory the tree is written to.
        backend: Database backend written into ``config.default.yaml``.

    Returns:
        The repository root.
    """
    (root / "etlalchemy").mkdir(parents=True)
    (root / "etlalchemy" / "__init__.py").write_text("VERSION = '1'\n", encoding="utf-8")
    (root / "pyproject.toml").write_text(
        "[project]\nname = 'etlalchemy'\nversion = '0.0.1'\n",
        encoding="utf-8",
    )
    (root / "uv.lock").write_text("# lock\n", encoding="utf-8")
    (root / "README.md").write_text("# app\n", encoding="utf-8")
    (root / "LICENSE").write_text("license\n", encoding="utf-8")
    bundle = root / "dist" / "ui"
    (bundle / "assets").mkdir(parents=True)
    (bundle / "index.html").write_text("<!doctype html>", encoding="utf-8")
    (bundle / "assets" / "index.js").write_text("console.log(1);", encoding="utf-8")
    database = (
        "database:\n  backend: postgres\n  postgres_dsn: postgresql://x@localhost/x\n"
        if backend == "postgres"
        else "database:\n  backend: sqlite\n  sqlite_path: ./app.db\n"
    )
    (root / "config.default.yaml").write_text(database, encoding="utf-8")
    return root


def make_options(root: Path, **overrides: Any) -> DeployOptions:
    """Returns deployment options pointing at a miniature repository.

    Args:
        root: Repository root created by :func:`make_repo`.
        **overrides: Fields to replace on the defaults.

    Returns:
        The options of one run.
    """
    values: dict[str, Any] = {
        "profile": "test-profile",
        "app_name": "etlalchemy",
        "workspace_path": "/Workspace/Users/user@example.com/etlalchemy",
        "source": root,
        "ui_dir": root / "dist" / "ui",
        "config_files": (),
        "command": ("uv", "run", "uvicorn", "etlalchemy.app.main:app"),
        "health_timeout_seconds": 120,
        "host": "https://adb-123.azuredatabricks.net",
        "assume_yes": True,
        "poll_interval_seconds": 0.0,
    }
    values.update(overrides)
    return DeployOptions(**values)


class FakeWorkspace:
    """In-memory :class:`~etlalchemy.app.deploy.workspace.WorkspaceApi`."""

    def __init__(self, *, app: dict[str, Any] | None = APP) -> None:
        """Creates the fake.

        Args:
            app: App object the workspace returns; ``None`` makes it unknown.
        """
        self.app = app
        self.files: dict[str, bytes] = {}
        self.directories: set[str] = set()
        self.uploads: list[str] = []
        self.deleted: list[str] = []
        self.deployments: list[tuple[str, str]] = []
        self.states: list[str] = ["SUCCEEDED"]

    async def current_user(self) -> str:
        """Returns the fake user name."""
        return "user@example.com"

    async def get_app(self, name: str) -> dict[str, Any]:
        """Returns the configured app or reports it as missing."""
        if self.app is None:
            msg = f"the Databricks app '{name}' does not exist"
            raise AppNotFoundError(msg)
        return dict(self.app)

    async def list_tree(self, root: str) -> dict[str, RemoteFile]:
        """Returns the fake tree below ``root``, keyed by relative path."""
        prefix = f"{root.rstrip('/')}/"
        found: dict[str, RemoteFile] = {}
        for path, content in self.files.items():
            if path.startswith(prefix):
                found[path[len(prefix) :]] = RemoteFile(
                    path=path,
                    object_type=FILE_OBJECT,
                    size=len(content),
                )
        for path in self.directories:
            if path.startswith(prefix):
                found[path[len(prefix) :]] = RemoteFile(
                    path=path,
                    object_type=DIRECTORY_OBJECT,
                )
        return found

    async def mkdirs(self, path: str) -> None:
        """Records a created folder."""
        self.directories.add(path)

    async def read_file(self, path: str) -> bytes | None:
        """Returns a recorded file."""
        return self.files.get(path)

    async def write_file(self, path: str, content: bytes) -> None:
        """Records a written file."""
        self.files[path] = content
        self.uploads.append(path)

    async def delete(self, path: str, *, recursive: bool = False) -> None:
        """Records a deletion."""
        del recursive
        self.files.pop(path, None)
        self.deleted.append(path)

    async def create_deployment(self, name: str, source_code_path: str) -> dict[str, Any]:
        """Records the deployment and returns its first status."""
        self.deployments.append((name, source_code_path))
        return {"deployment_id": "deployment-1", "status": {"state": self.states[0]}}

    async def get_deployment(self, name: str, deployment_id: str) -> dict[str, Any]:
        """Returns the next scripted deployment state."""
        del name, deployment_id
        state = self.states[min(1, len(self.states) - 1)]
        if len(self.states) > 1:
            self.states.pop(0)
        return {"deployment_id": "deployment-1", "status": {"state": state}}
