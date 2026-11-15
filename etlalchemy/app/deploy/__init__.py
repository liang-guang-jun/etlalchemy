"""Deployment tooling of the assembly layer.

The command line only orchestrates: credential resolution lives in
:mod:`etlalchemy.app.deploy.auth`, the REST calls in
:mod:`etlalchemy.app.deploy.workspace`, the staged tree in
:mod:`etlalchemy.app.deploy.staging` and the incremental comparison in
:mod:`etlalchemy.app.deploy.snapshot`.
"""

from __future__ import annotations

from etlalchemy.app.deploy.errors import (
    AppNotFoundError,
    DeployError,
    DeploymentFailedError,
    ProfileResolutionError,
    UploadError,
)
from etlalchemy.app.deploy.models import (
    ChangeKind,
    DeployPlan,
    DeployReport,
    FileChange,
    LocalFile,
    RemoteFile,
)
from etlalchemy.app.deploy.runner import DeployOptions, deploy_databricks_apps, run_deploy
from etlalchemy.app.deploy.workspace import AsyncWorkspaceApi, WorkspaceApi

__all__ = [
    "AppNotFoundError",
    "AsyncWorkspaceApi",
    "ChangeKind",
    "DeployError",
    "DeployOptions",
    "DeployPlan",
    "DeployReport",
    "DeploymentFailedError",
    "FileChange",
    "LocalFile",
    "ProfileResolutionError",
    "RemoteFile",
    "UploadError",
    "WorkspaceApi",
    "deploy_databricks_apps",
    "run_deploy",
]
