"""Errors the deployment tooling reports.

Every error is a :class:`DeployError` so the command line can map the whole
family to one exit code and one message format, mirroring how the IAM command
groups its aggregate errors.
"""

from __future__ import annotations


class DeployError(RuntimeError):
    """Raised when a deployment cannot be completed."""


class ProfileResolutionError(DeployError):
    """Raised when the Databricks CLI profile cannot supply usable credentials."""


class AppNotFoundError(DeployError):
    """Raised when the target Databricks app does not exist."""


class UploadError(DeployError):
    """Raised when a file cannot be written to the workspace."""


class DeploymentFailedError(DeployError):
    """Raised when the platform reports a failed deployment."""
