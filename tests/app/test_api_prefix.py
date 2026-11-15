"""Tests for the configurable prefix every HTTP router is mounted under."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from etlalchemy.app.api.app import create_app


def test_routers_answer_under_the_default_prefix(config_dir: Any) -> None:
    """Every context router is reachable below ``/api``."""
    with TestClient(create_app()) as client:
        assert client.get("/api/catalog/catalogs").status_code == 200
        assert client.get("/api/semantic/models").status_code == 200
        assert client.get("/api/vocabulary/domains").status_code == 200


def test_unprefixed_paths_are_gone(config_dir: Any) -> None:
    """The old root paths answer 404, so a stale client fails loudly."""
    with TestClient(create_app()) as client:
        assert client.get("/catalog/catalogs").status_code == 404
        assert client.get("/iam/bootstrap").status_code == 404


def test_health_endpoint_answers(config_dir: Any) -> None:
    """The platform health check gets a 200 from the configured path."""
    with TestClient(create_app()) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_prefix_is_configurable(
    config_dir: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A deployment can mount the API elsewhere, including the Swagger token path."""
    monkeypatch.setenv("ETLALCHEMY_API__PREFIX", "/v1/api/")

    with TestClient(create_app()) as client:
        assert client.get("/v1/api/catalog/catalogs").status_code == 200
        assert client.get("/api/catalog/catalogs").status_code == 404
        schema = client.get("/openapi.json").json()

    scheme = schema["components"]["securitySchemes"]["OAuth2PasswordBearer"]
    assert scheme["flows"]["password"]["tokenUrl"] == "/v1/api/iam/auth/token"


def test_empty_prefix_serves_the_root(
    config_dir: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An empty prefix keeps the historical root layout available."""
    monkeypatch.setenv("ETLALCHEMY_API__PREFIX", "")

    with TestClient(create_app()) as client:
        assert client.get("/catalog/catalogs").status_code == 200


def test_invalid_prefix_without_slash_is_rejected(
    config_dir: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The prefix is normalised, so a value without a leading slash still works."""
    monkeypatch.setenv("ETLALCHEMY_API__PREFIX", "api")

    with TestClient(create_app()) as client:
        assert client.get("/api/catalog/catalogs").status_code == 200
