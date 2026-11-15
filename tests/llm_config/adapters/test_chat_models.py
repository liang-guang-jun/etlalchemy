"""Tests of the chat model adapters."""

from __future__ import annotations

from typing import Any

import pytest
from langchain_core.messages import AIMessageChunk

import etlalchemy.llm_config.adapters.chat_models as chat_models
from etlalchemy.llm_config.adapters.chat_models import build_chat_model, coerce_option
from etlalchemy.llm_config.aggregates.errors import (
    InvalidProviderKindError,
    MissingAdapterError,
    MissingModelError,
    ProviderCredentialError,
)


def raw_chunk(**delta: Any) -> dict[str, Any]:
    """Builds one raw Chat Completions chunk with the given delta."""
    return {"choices": [{"index": 0, "delta": delta}]}


def test_coerce_option_reads_scalars() -> None:
    """A textual option becomes the scalar the client expects."""
    assert coerce_option("true") is True
    assert coerce_option(" 12 ") == 12
    assert coerce_option("0.5") == 0.5
    assert coerce_option("fast") == "fast"


def test_the_reasoning_of_a_chunk_is_kept() -> None:
    """The provider's thinking survives the conversion to a message chunk."""
    model = build_chat_model(kind="openai", credential="test-key", default_model="m")
    generation = model._convert_chunk_to_generation_chunk(  # noqa: SLF001
        raw_chunk(content="", reasoning_content="hmm"),
        AIMessageChunk,
        None,
    )

    assert generation is not None
    assert generation.message.additional_kwargs["reasoning_content"] == "hmm"


def test_the_answer_of_a_chunk_is_untouched() -> None:
    """A regular delta keeps its text and gains no reasoning."""
    model = build_chat_model(kind="openai", credential="test-key", default_model="m")
    generation = model._convert_chunk_to_generation_chunk(  # noqa: SLF001
        raw_chunk(content="hello"),
        AIMessageChunk,
        None,
    )

    assert generation is not None
    assert generation.message.content == "hello"
    assert "reasoning_content" not in generation.message.additional_kwargs


def test_a_profile_provider_builds_a_workspace_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A profile provider passes the SDK client instead of an API key."""
    captured: dict[str, Any] = {}

    class FakeClient:
        def __init__(self, **kwargs: Any) -> None:
            captured["client"] = kwargs

    class FakeChat:
        def __init__(self, **kwargs: Any) -> None:
            captured["chat"] = kwargs

    monkeypatch.setattr(chat_models, "_workspace_client_class", lambda: FakeClient)
    monkeypatch.setattr(chat_models, "_databricks_class", lambda: FakeChat)

    model = build_chat_model(
        kind="databricks_ai_gateway",
        credential=None,
        default_model="databricks-claude-sonnet-4-5",
        profile="team",
        options={"temperature": "0.5"},
    )

    assert isinstance(model, FakeChat)
    assert captured["client"] == {"profile": "team"}
    assert captured["chat"]["model"] == "databricks-claude-sonnet-4-5"
    assert isinstance(captured["chat"]["workspace_client"], FakeClient)
    assert captured["chat"]["temperature"] == 0.5
    assert "api_key" not in captured["chat"]


def test_an_empty_profile_uses_the_sdk_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``profile:`` lets the SDK resolve the profile itself."""
    captured: dict[str, Any] = {}

    class FakeClient:
        def __init__(self, **kwargs: Any) -> None:
            captured["client"] = kwargs

    class FakeChat:
        def __init__(self, **kwargs: Any) -> None:
            captured["chat"] = kwargs

    monkeypatch.setattr(chat_models, "_workspace_client_class", lambda: FakeClient)
    monkeypatch.setattr(chat_models, "_databricks_class", lambda: FakeChat)

    build_chat_model(
        kind="databricks_ai_gateway",
        credential=None,
        default_model="m",
        profile="",
    )

    assert captured["client"] == {"profile": None}


def test_a_profile_needs_a_model() -> None:
    """A profile does not name the serving endpoint to run."""
    with pytest.raises(MissingModelError):
        build_chat_model(kind="databricks_ai_gateway", credential=None, profile="team")


def test_a_profile_is_only_supported_by_the_databricks_kind() -> None:
    """An OpenAI chat model cannot use a Databricks profile."""
    with pytest.raises(InvalidProviderKindError, match="profile"):
        build_chat_model(
            kind="openai",
            credential=None,
            default_model="m",
            profile="team",
        )


def test_a_profile_falls_back_to_the_serving_endpoints_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without ``databricks-langchain`` the profile still builds a chat model.

    ``databricks-langchain`` currently conflicts with the repository's ``mcp``
    2.x, so the profile path uses the SDK to resolve the bearer token and the
    OpenAI-compatible serving-endpoints API.
    """
    captured: dict[str, Any] = {}

    class FakeConfig:
        host = "https://example.cloud.databricks.com/"

        def authenticate(self) -> dict[str, str]:
            return {"Authorization": "Bearer profile-token"}

    class FakeClient:
        def __init__(self, **kwargs: Any) -> None:
            self.config = FakeConfig()

    class FakeChat:
        def __init__(self, **kwargs: Any) -> None:
            captured["chat"] = kwargs

    monkeypatch.setattr(chat_models, "_workspace_client_class", lambda: FakeClient)
    monkeypatch.setattr(chat_models, "_databricks_class", lambda: None)
    monkeypatch.setattr(chat_models, "_reasoning_class", lambda: FakeChat)

    model = build_chat_model(
        kind="databricks_ai_gateway",
        credential=None,
        default_model="databricks-claude-sonnet-4-5",
        profile="team",
        options={"temperature": "0.2"},
    )

    assert isinstance(model, FakeChat)
    kwargs = captured["chat"]
    assert kwargs["model"] == "databricks-claude-sonnet-4-5"
    assert kwargs["base_url"] == (
        "https://example.cloud.databricks.com/serving-endpoints"
    )
    assert kwargs["api_key"].get_secret_value() == "profile-token"
    assert kwargs["temperature"] == 0.2


def test_a_profile_without_the_sdk_extra_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A profile needs ``databricks-sdk`` to resolve its credentials."""

    def missing(name: str) -> Any:
        raise ImportError(name)

    monkeypatch.setattr(chat_models.importlib, "import_module", missing)

    with pytest.raises(MissingAdapterError, match="'databricks' extra"):
        build_chat_model(
            kind="databricks_ai_gateway",
            credential=None,
            default_model="m",
            profile="team",
        )


def test_a_profile_without_a_bearer_token_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A profile that yields no authenticating header cannot reach the API."""

    class FakeConfig:
        host = "https://example.test"

        def authenticate(self) -> dict[str, str]:
            return {}

    class FakeClient:
        def __init__(self, **kwargs: Any) -> None:
            self.config = FakeConfig()

    monkeypatch.setattr(chat_models, "_workspace_client_class", lambda: FakeClient)
    monkeypatch.setattr(chat_models, "_databricks_class", lambda: None)

    with pytest.raises(ProviderCredentialError, match="bearer token"):
        build_chat_model(
            kind="databricks_ai_gateway",
            credential=None,
            default_model="m",
            profile="team",
        )


def test_an_openai_provider_needs_a_key() -> None:
    """A non-profile provider without a credential is a caller error."""
    with pytest.raises(ProviderCredentialError):
        build_chat_model(kind="openai", credential=None, default_model="m")
