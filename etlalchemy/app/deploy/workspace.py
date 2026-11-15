"""Asynchronous client of the Databricks workspace and apps REST APIs.

The deployment is one sequence of independent HTTP calls, so the client is a thin
async wrapper over ``httpx``: the directory listing walks the tree level by level
and fetches each level concurrently, uploads run concurrently under one semaphore
and every call is retried on a transient status. Nothing here knows about the
CLI profile; :mod:`etlalchemy.app.deploy.auth` resolves the credentials.
"""

from __future__ import annotations

import asyncio
import base64
from collections.abc import Mapping
from typing import Any, Protocol

import httpx

from etlalchemy.app.deploy.errors import AppNotFoundError, DeployError, UploadError
from etlalchemy.app.deploy.models import DIRECTORY_OBJECT, RemoteFile

IMPORT_LIMIT_BYTES = 10 * 1024 * 1024
"""Largest file the workspace import endpoint accepts, in bytes."""

REQUEST_TIMEOUT_SECONDS = 60.0
"""Timeout of one HTTP call."""

RETRY_ATTEMPTS = 3
"""Attempts of one call before the deployment fails."""

RETRY_BACKOFF_SECONDS = 0.5
"""Base of the exponential backoff between attempts."""

RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})
"""Statuses worth a retry."""

WORKSPACE_LIST = "/api/2.0/workspace/list"
WORKSPACE_MKDIRS = "/api/2.0/workspace/mkdirs"
WORKSPACE_IMPORT = "/api/2.0/workspace/import"
WORKSPACE_EXPORT = "/api/2.0/workspace/export"
WORKSPACE_DELETE = "/api/2.0/workspace/delete"
CURRENT_USER = "/api/2.0/preview/scim/v2/Me"
APPS = "/api/2.0/apps"


class WorkspaceApi(Protocol):
    """Operations the deployment needs from the workspace.

    Declaring them as a protocol keeps the orchestration testable: the tests
    drive it with an in-memory fake instead of an HTTP server.
    """

    async def current_user(self) -> str:
        """Returns the user name of the profile, for the default folder."""
        ...

    async def get_app(self, name: str) -> dict[str, Any]:
        """Returns the app, or raises :class:`AppNotFoundError`."""
        ...

    async def list_tree(self, root: str) -> dict[str, RemoteFile]:
        """Returns every object below ``root`` keyed by its relative path."""
        ...

    async def mkdirs(self, path: str) -> None:
        """Creates a folder and its parents."""
        ...

    async def read_file(self, path: str) -> bytes | None:
        """Returns a file's content, or ``None`` when it does not exist."""
        ...

    async def write_file(self, path: str, content: bytes) -> None:
        """Writes a file, overwriting an existing object."""
        ...

    async def delete(self, path: str, *, recursive: bool = False) -> None:
        """Deletes an object or a whole folder."""
        ...

    async def create_deployment(self, name: str, source_code_path: str) -> dict[str, Any]:
        """Starts a snapshot deployment from a workspace folder."""
        ...

    async def get_deployment(self, name: str, deployment_id: str) -> dict[str, Any]:
        """Returns one deployment, including its status."""
        ...


class AsyncWorkspaceApi:
    """HTTP client of a Databricks workspace, scoped to one profile."""

    def __init__(
        self,
        *,
        host: str,
        headers: Mapping[str, str],
        client: httpx.AsyncClient | None = None,
        concurrency: int = 8,
        timeout: float = REQUEST_TIMEOUT_SECONDS,
    ) -> None:
        """Creates the client.

        Args:
            host: Workspace base URL, without a trailing slash.
            headers: Authentication headers the SDK produced for the profile.
            client: Pre-built client, injected by the tests; the caller keeps
                ownership of it.
            concurrency: Number of requests in flight at once.
            timeout: Timeout of one request, in seconds.
        """
        self._client = client or httpx.AsyncClient(
            base_url=host,
            headers=dict(headers),
            timeout=timeout,
        )
        self._owns_client = client is None
        self._semaphore = asyncio.Semaphore(concurrency)

    async def aclose(self) -> None:
        """Closes the HTTP client this instance created."""
        if self._owns_client:
            await self._client.aclose()

    async def current_user(self) -> str:
        """Returns the user name of the profile, for the default folder.

        Returns:
            The workspace user name, for example ``user@example.com``.

        Raises:
            DeployError: When the response names no user.
        """
        response = await self._request("GET", CURRENT_USER)
        self._raise_for(response, "reading the current user")
        name = str(self._json(response).get("userName") or "").strip()
        if not name:
            msg = "the workspace did not report the user name of the profile"
            raise DeployError(msg)
        return name

    async def get_app(self, name: str) -> dict[str, Any]:
        """Returns the app the deployment targets.

        Args:
            name: App name.

        Returns:
            The app object the API returned.

        Raises:
            AppNotFoundError: When the workspace has no app with that name.
        """
        response = await self._request("GET", f"{APPS}/{name}")
        if response.status_code == httpx.codes.NOT_FOUND:
            msg = (
                f"the Databricks app '{name}' does not exist; create it first with "
                f"'databricks apps create {name}'"
            )
            raise AppNotFoundError(msg)
        self._raise_for(response, f"reading the app {name}")
        return self._json(response)

    async def list_tree(self, root: str) -> dict[str, RemoteFile]:
        """Walks a workspace folder and returns its relative tree.

        Args:
            root: Absolute workspace path of the app folder.

        Returns:
            Every object below ``root`` keyed by its path relative to ``root``;
            an empty mapping when the folder does not exist yet.
        """
        found: dict[str, RemoteFile] = {}
        pending = [root.rstrip("/")]
        while pending:
            listings = await asyncio.gather(
                *(self._list_directory(path) for path in pending),
                return_exceptions=False,
            )
            pending = []
            for entries in listings:
                for entry in entries:
                    if entry.path in found:
                        continue
                    found[entry.path] = entry
                    if entry.object_type == DIRECTORY_OBJECT:
                        pending.append(entry.path)
        prefix = f"{root.rstrip('/')}/"
        return {
            path[len(prefix) :]: entry for path, entry in found.items() if path.startswith(prefix)
        }

    async def mkdirs(self, path: str) -> None:
        """Creates a workspace folder and its parents.

        Args:
            path: Absolute workspace path.
        """
        response = await self._request("POST", WORKSPACE_MKDIRS, json={"path": path})
        self._raise_for(response, f"creating the folder {path}")

    async def read_file(self, path: str) -> bytes | None:
        """Reads a workspace file.

        Args:
            path: Absolute workspace path.

        Returns:
            The content, or ``None`` when the object does not exist.
        """
        response = await self._request(
            "GET",
            WORKSPACE_EXPORT,
            params={"path": path, "format": "AUTO", "direct_download": "true"},
        )
        if response.status_code == httpx.codes.NOT_FOUND:
            return None
        self._raise_for(response, f"reading {path}")
        return response.content

    async def write_file(self, path: str, content: bytes) -> None:
        """Writes a workspace file, overwriting the existing object.

        Args:
            path: Absolute workspace path.
            content: Raw file content.

        Raises:
            UploadError: When the file exceeds the import limit or the API
                rejects the write.
        """
        if len(content) > IMPORT_LIMIT_BYTES:
            msg = (
                f"{path} is {len(content)} bytes and the workspace import limit is "
                f"{IMPORT_LIMIT_BYTES} bytes; split the bundle or shrink the asset"
            )
            raise UploadError(msg)
        response = await self._request(
            "POST",
            WORKSPACE_IMPORT,
            json={
                "path": path,
                "format": "RAW",
                "content": base64.b64encode(content).decode("ascii"),
                "overwrite": True,
            },
        )
        if response.status_code >= httpx.codes.BAD_REQUEST:
            raise UploadError(
                f"writing {path} failed with {response.status_code}: {self._detail(response)}",
            )

    async def delete(self, path: str, *, recursive: bool = False) -> None:
        """Deletes a workspace object or folder.

        Args:
            path: Absolute workspace path.
            recursive: Whether a folder may be removed with its content.
        """
        response = await self._request(
            "POST",
            WORKSPACE_DELETE,
            json={"path": path, "recursive": recursive},
        )
        self._raise_for(response, f"deleting {path}")

    async def create_deployment(self, name: str, source_code_path: str) -> dict[str, Any]:
        """Starts a snapshot deployment of a workspace folder.

        Args:
            name: App name.
            source_code_path: Folder holding the deployed source.

        Returns:
            The deployment the platform created.
        """
        response = await self._request(
            "POST",
            f"{APPS}/{name}/deployments",
            json={"source_code_path": source_code_path, "mode": "SNAPSHOT"},
        )
        self._raise_for(response, f"deploying {name}")
        return self._json(response)

    async def get_deployment(self, name: str, deployment_id: str) -> dict[str, Any]:
        """Reads the status of one deployment.

        Args:
            name: App name.
            deployment_id: Deployment id returned by :meth:`create_deployment`.

        Returns:
            The deployment object.
        """
        response = await self._request("GET", f"{APPS}/{name}/deployments/{deployment_id}")
        self._raise_for(response, f"reading deployment {deployment_id}")
        return self._json(response)

    async def _list_directory(self, path: str) -> list[RemoteFile]:
        """Lists one folder of the workspace.

        Args:
            path: Absolute workspace path.

        Returns:
            The objects the folder holds; empty when the folder does not exist.
        """
        response = await self._request("GET", WORKSPACE_LIST, params={"path": path})
        if response.status_code == httpx.codes.NOT_FOUND:
            return []
        self._raise_for(response, f"listing {path}")
        objects = self._json(response).get("objects") or []
        return [
            RemoteFile(
                path=str(entry.get("path", "")),
                object_type=str(entry.get("object_type", "")),
                size=entry.get("size") if isinstance(entry.get("size"), int) else None,
            )
            for entry in objects
            if isinstance(entry, dict) and entry.get("path")
        ]

    async def _request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        """Sends one request, retrying a transient status with backoff.

        Args:
            method: HTTP method.
            url: Path below the workspace host.
            **kwargs: Arguments forwarded to ``httpx``.

        Returns:
            The last response, successful or not.
        """
        response: httpx.Response | None = None
        for attempt in range(RETRY_ATTEMPTS):
            async with self._semaphore:
                response = await self._client.request(method, url, **kwargs)
            if response.status_code not in RETRYABLE_STATUS:
                return response
            if attempt + 1 < RETRY_ATTEMPTS:
                await asyncio.sleep(RETRY_BACKOFF_SECONDS * (2**attempt))
        if response is None:  # pragma: no cover - RETRY_ATTEMPTS is at least one
            msg = f"{method} {url} was never sent"
            raise DeployError(msg)
        return response

    def _raise_for(self, response: httpx.Response, action: str) -> None:
        """Raises a deployment error for an unsuccessful response.

        Args:
            response: Response to inspect.
            action: Description used in the message.

        Raises:
            DeployError: When the response status is 400 or above.
        """
        if response.status_code < httpx.codes.BAD_REQUEST:
            return
        msg = f"{action} failed with {response.status_code}: {self._detail(response)}"
        raise DeployError(msg)

    @staticmethod
    def _json(response: httpx.Response) -> dict[str, Any]:
        """Decodes a JSON object, tolerating an empty or malformed body.

        Args:
            response: Response to decode.

        Returns:
            The decoded mapping, or an empty one.
        """
        try:
            data: Any = response.json()
        except ValueError:
            return {}
        return data if isinstance(data, dict) else {}

    @staticmethod
    def _detail(response: httpx.Response) -> str:
        """Extracts a short error description from a response.

        Args:
            response: Failed response.

        Returns:
            The platform message, the error code, or the first bytes of the body.
        """
        payload: Any
        try:
            payload = response.json()
        except ValueError:
            payload = None
        if isinstance(payload, dict):
            detail = payload.get("message") or payload.get("error_code")
            if detail:
                return str(detail)
        return response.text[:200].strip() or response.reason_phrase
