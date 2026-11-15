"""Tests for the asynchronous workspace client."""

from __future__ import annotations

import base64
import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from etlalchemy.app.deploy import workspace
from etlalchemy.app.deploy.errors import AppNotFoundError, DeployError, UploadError
from etlalchemy.app.deploy.workspace import AsyncWorkspaceApi

HOST = "https://adb-123.azuredatabricks.net"
ROOT = "/Workspace/Users/user@example.com/etlalchemy"
"""Folder every test works in."""


Handler = Callable[[httpx.Request], httpx.Response]


def api(handler: Handler) -> AsyncWorkspaceApi:
    """Builds a client whose transport is the given handler."""
    client = httpx.AsyncClient(
        base_url=HOST,
        headers={"Authorization": "Bearer token"},
        transport=httpx.MockTransport(handler),
    )
    return AsyncWorkspaceApi(host=HOST, headers={}, client=client)


def json_response(payload: dict[str, Any]) -> httpx.Response:
    """Builds a JSON response."""
    return httpx.Response(200, json=payload)


async def test_list_tree_walks_every_level_and_returns_relative_paths() -> None:
    """The recursive listing keys the tree the way the diff expects."""
    listings = {
        ROOT: [
            {"path": f"{ROOT}/etlalchemy", "object_type": "DIRECTORY"},
            {"path": f"{ROOT}/app.yaml", "object_type": "FILE", "size": 12},
        ],
        f"{ROOT}/etlalchemy": [
            {"path": f"{ROOT}/etlalchemy/__init__.py", "object_type": "FILE", "size": 3},
        ],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.params["path"]
        return json_response({"objects": listings.get(path, [])})

    client = api(handler)
    try:
        tree = await client.list_tree(ROOT)
    finally:
        await client.aclose()

    assert sorted(tree) == ["app.yaml", "etlalchemy", "etlalchemy/__init__.py"]
    assert tree["app.yaml"].size == 12
    assert tree["etlalchemy"].object_type == "DIRECTORY"


async def test_missing_folder_lists_as_empty() -> None:
    """The first deployment finds no folder and must not fail."""

    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(404, json={"error_code": "RESOURCE_DOES_NOT_EXIST"})

    client = api(handler)
    try:
        assert await client.list_tree(ROOT) == {}
    finally:
        await client.aclose()


async def test_write_file_imports_a_raw_overwriting_file() -> None:
    """``RAW`` keeps a ``.py`` file a file instead of turning it into a notebook."""
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(200, json={})

    client = api(handler)
    try:
        await client.write_file(f"{ROOT}/app.yaml", b"command: []\n")
    finally:
        await client.aclose()

    assert captured["path"] == f"{ROOT}/app.yaml"
    assert captured["format"] == "RAW"
    assert captured["overwrite"] is True
    assert base64.b64decode(captured["content"]) == b"command: []\n"


async def test_write_file_rejects_a_file_above_the_import_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The platform rejects the call, so the client reports it locally."""
    monkeypatch.setattr(workspace, "IMPORT_LIMIT_BYTES", 4)

    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover - never called
        return httpx.Response(200, json={})

    client = api(handler)
    try:
        with pytest.raises(UploadError, match="import limit"):
            await client.write_file(f"{ROOT}/big.js", b"12345")
    finally:
        await client.aclose()


async def test_unknown_app_is_reported_with_the_create_hint() -> None:
    """A typo in ``--app-name`` fails before any upload."""

    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(404, json={"error_code": "RESOURCE_DOES_NOT_EXIST"})

    client = api(handler)
    try:
        with pytest.raises(AppNotFoundError, match="databricks apps create"):
            await client.get_app("missing")
    finally:
        await client.aclose()


async def test_deployment_is_created_as_a_snapshot() -> None:
    """The source folder is snapshotted, so a later local edit cannot leak in."""
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return json_response({"deployment_id": "abc", "status": {"state": "PENDING"}})

    client = api(handler)
    try:
        deployment = await client.create_deployment("etlalchemy", ROOT)
    finally:
        await client.aclose()

    assert captured == {"source_code_path": ROOT, "mode": "SNAPSHOT"}
    assert deployment["deployment_id"] == "abc"


async def test_transient_failures_are_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    """A throttled call succeeds on the next attempt instead of failing the run."""
    monkeypatch.setattr(workspace, "RETRY_BACKOFF_SECONDS", 0.0)
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        if calls["count"] == 1:
            return httpx.Response(429, json={"message": "slow down"})
        return json_response({"userName": "user@example.com"})

    client = api(handler)
    try:
        assert await client.current_user() == "user@example.com"
    finally:
        await client.aclose()

    assert calls["count"] == 2


async def test_failed_call_reports_the_platform_message() -> None:
    """The operator sees what the workspace said, not just the status code."""

    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(403, json={"message": "PERMISSION_DENIED: no access"})

    client = api(handler)
    try:
        with pytest.raises(DeployError, match="PERMISSION_DENIED"):
            await client.mkdirs(f"{ROOT}/dist")
    finally:
        await client.aclose()


async def test_missing_file_reads_as_none() -> None:
    """A folder without a manifest is not an error."""

    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(404, json={"error_code": "RESOURCE_DOES_NOT_EXIST"})

    client = api(handler)
    try:
        assert await client.read_file(f"{ROOT}/.etlalchemy-deploy.json") is None
    finally:
        await client.aclose()
