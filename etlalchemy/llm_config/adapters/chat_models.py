"""Builds the chat model of one LLM provider kind.

The provider packages are optional: ``openai`` needs the ``agent-openai`` extra
and ``databricks_ai_gateway`` prefers ``agent-databricks`` but falls back to the
OpenAI-compatible serving endpoint, so a missing extra never blocks startup. A
profile provider resolves its credentials with ``databricks-sdk`` and uses the
same OpenAI-compatible client when ``databricks-langchain`` cannot be imported.
"""

from __future__ import annotations

import importlib
from collections.abc import Mapping
from typing import Any, cast

from langchain_core.language_models import BaseChatModel
from pydantic import SecretStr

from etlalchemy.llm_config.aggregates.errors import (
    InvalidProviderKindError,
    MissingAdapterError,
    MissingModelError,
    ProviderCredentialError,
)
from etlalchemy.llm_config.aggregates.types import PROFILE_KINDS

DEFAULT_OPENAI_MODEL = "gpt-4o-mini"
"""Model used when neither the request nor the provider names one."""


def coerce_option(value: str) -> Any:
    """Converts one textual option into the scalar the client expects.

    Args:
        value: Option value as it is stored on the provider aggregate.

    Returns:
        A ``bool``, ``int``, ``float`` or the unchanged string.
    """
    text = value.strip()
    lowered = text.lower()
    if lowered in {"true", "false"}:
        return lowered == "true"
    try:
        return int(text)
    except ValueError:
        pass
    try:
        return float(text)
    except ValueError:
        return value


def _openai_class() -> Any:
    """Returns the OpenAI chat model class, or raises when the extra is absent."""
    try:
        from langchain_openai import ChatOpenAI
    except ImportError as exc:
        msg = "the 'agent-openai' extra is required for the openai provider kind"
        raise MissingAdapterError(msg) from exc
    return ChatOpenAI


_DATABRICKS_CLASS: Any | None = None
"""Cached Databricks chat model class; ``None`` when it cannot be imported."""

_DATABRICKS_IMPORTED = False
"""Whether the optional import was already attempted."""


def _databricks_class() -> Any | None:
    """Returns the Databricks chat model class, or ``None`` when it is absent."""
    global _DATABRICKS_CLASS, _DATABRICKS_IMPORTED
    if not _DATABRICKS_IMPORTED:
        try:
            from databricks_langchain import ChatDatabricks
        except ImportError:
            # The extra is optional, and its current release conflicts with the
            # repository's ``mcp`` 2.x, so a failed import is expected.
            _DATABRICKS_CLASS = None
        else:
            _DATABRICKS_CLASS = ChatDatabricks
        _DATABRICKS_IMPORTED = True
    return _DATABRICKS_CLASS


def _workspace_client_class() -> Any:
    """Imports the Databricks SDK lazily so it stays an optional dependency."""
    try:
        module = importlib.import_module("databricks.sdk")
    except ImportError as exc:
        msg = "the 'databricks' extra is required for a profile provider"
        raise MissingAdapterError(msg) from exc
    return module.WorkspaceClient


def _workspace_client(profile: str) -> Any:
    """Builds a client that authenticates with a local Databricks CLI profile."""
    return _workspace_client_class()(profile=profile or None)


def _profile_host(client: Any) -> str:
    """Returns the workspace host recorded by the profile."""
    host = (getattr(getattr(client, "config", None), "host", None) or "").strip()
    if not host:
        msg = "the Databricks CLI profile does not record a workspace host"
        raise ProviderCredentialError(msg)
    return host.rstrip("/")


def _profile_token(client: Any) -> str:
    """Returns the bearer token the SDK resolved for the profile.

    A profile may authenticate with OAuth instead of a static PAT, so the token
    is taken from the SDK's authenticating headers rather than ``config.token``.
    """
    config = getattr(client, "config", None)
    authenticate = getattr(config, "authenticate", None)
    headers = authenticate() if callable(authenticate) else {}
    authorization = str(headers.get("Authorization") or headers.get("authorization") or "")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        msg = "the Databricks CLI profile did not produce a bearer token"
        raise ProviderCredentialError(msg)
    return token.strip()


def _profile_openai_chat_model(
    client: Any,
    default_model: str,
    extra: dict[str, Any],
) -> BaseChatModel:
    """Builds the OpenAI-compatible serving-endpoints client of a profile.

    This is the fallback used when ``databricks-langchain`` is absent or cannot
    be imported (it currently conflicts with the repository's ``mcp`` 2.x). The
    SDK still resolves the profile credentials, and the token is refreshed on
    every run because the factory builds the model per run.
    """
    try:
        chat_openai = _reasoning_class()
    except MissingAdapterError as exc:
        msg = "a profile provider needs langchain-openai: install the 'agent-openai' extra"
        raise MissingAdapterError(msg) from exc
    chat: BaseChatModel = chat_openai(
        model=default_model,
        api_key=SecretStr(_profile_token(client)),
        base_url=f"{_profile_host(client)}/serving-endpoints",
        **extra,
    )
    return chat


def _profile_chat_model(
    *,
    kind: str,
    profile: str,
    default_model: str,
    extra: dict[str, Any],
) -> BaseChatModel:
    """Builds the chat model of a provider that authenticates with a profile.

    Args:
        kind: Provider kind; only the Databricks gateway understands profiles.
        profile: CLI profile name, empty for the SDK default.
        default_model: Serving endpoint name; a profile does not name one.
        extra: Already coerced model options.

    Returns:
        A chat model bound to the workspace client of the profile.

    Raises:
        InvalidProviderKindError: If the kind does not support profiles.
        MissingModelError: If no model was configured.
        MissingAdapterError: If the Databricks SDK (or an OpenAI-compatible
            LangChain client) is not installed.
        ProviderCredentialError: If the profile yields no bearer token or host.
    """
    if kind not in PROFILE_KINDS:
        msg = f"provider kind {kind!r} does not support a profile credential"
        raise InvalidProviderKindError(msg)
    if not default_model.strip():
        msg = "a profile provider requires an explicit default_model"
        raise MissingModelError(msg)
    client = _workspace_client(profile)
    chat_databricks = _databricks_class()
    if chat_databricks is not None:
        try:
            chat: BaseChatModel = chat_databricks(
                model=default_model,
                workspace_client=client,
                **extra,
            )
        except TypeError:
            # An older databricks-langchain without ``workspace_client``.
            pass
        else:
            return chat
    return _profile_openai_chat_model(client, default_model, extra)


def _reasoning_text(chunk: Mapping[str, Any]) -> str:
    """Returns the thinking a provider streamed in one raw chunk, if any.

    Args:
        chunk: Raw Chat Completions chunk of the provider.

    Returns:
        The ``reasoning_content`` delta, or an empty string.
    """
    choices = chunk.get("choices") or (chunk.get("chunk") or {}).get("choices") or []
    for choice in choices:
        delta = choice.get("delta") or {}
        text = delta.get("reasoning_content")
        if isinstance(text, str) and text:
            return text
    return ""


class _ReasoningChunkMixin:
    """Keeps the thinking a provider streams on the chunk it belongs to.

    ``ChatOpenAI`` copies only ``function_call`` into ``additional_kwargs`` when
    it turns a raw delta into a chunk, so a DeepSeek-style ``reasoning_content``
    would be dropped before the agent sees it. The mixin re-attaches the text;
    the agent runtime splits it apart from the answer.
    """

    def _convert_chunk_to_generation_chunk(
        self,
        chunk: dict[str, Any],
        default_chunk_class: type,
        base_generation_info: dict[str, Any] | None,
    ) -> Any:
        """Converts one raw chunk, preserving its reasoning text."""
        # The real superclass is the installed ``ChatOpenAI``, which mypy cannot
        # see through the mixin, so the base method is reached through Any.
        base = cast(Any, super())
        generation = base._convert_chunk_to_generation_chunk(
            chunk,
            default_chunk_class,
            base_generation_info,
        )
        text = _reasoning_text(chunk)
        if generation is not None and text:
            generation.message.additional_kwargs["reasoning_content"] = text
        return generation


def _reasoning_class() -> Any:
    """Returns an OpenAI chat model that keeps the provider's thinking."""
    chat_openai = _openai_class()
    return type("ReasoningChatOpenAI", (_ReasoningChunkMixin, chat_openai), {})


def build_chat_model(
    *,
    kind: str,
    credential: str | None,
    default_model: str = "",
    endpoint: str | None = None,
    options: Mapping[str, str] | None = None,
    profile: str | None = None,
) -> BaseChatModel:
    """Builds the chat model of one provider.

    Args:
        kind: Provider kind, ``openai`` or ``databricks_ai_gateway``.
        credential: Plaintext API key; ``None`` when a profile is used. Never logged.
        default_model: Model the provider prefers.
        endpoint: Base URL, required by the Databricks gateway without a profile.
        options: Extra model options, coerced to scalars.
        profile: Local Databricks CLI profile name; ``""`` means the SDK default.

    Returns:
        A chat model ready to bind tools.

    Raises:
        InvalidProviderKindError: If the kind is unknown.
        MissingAdapterError: If the provider package of the kind is not installed.
        MissingModelError: If a profile provider does not name its model.
        ProviderCredentialError: If a non-profile provider carries no API key.
    """
    extra = {key: coerce_option(value) for key, value in (options or {}).items()}
    if profile is not None:
        return _profile_chat_model(
            kind=kind,
            profile=profile,
            default_model=default_model,
            extra=extra,
        )
    if credential is None:
        msg = f"provider kind {kind!r} needs an API key or a profile"
        raise ProviderCredentialError(msg)
    model = default_model or DEFAULT_OPENAI_MODEL
    if kind == "openai":
        chat_openai = _reasoning_class()
        kwargs: dict[str, Any] = {"model": model, "api_key": SecretStr(credential), **extra}
        if endpoint:
            kwargs["base_url"] = endpoint
        chat: BaseChatModel = chat_openai(**kwargs)
        return chat
    if kind == "databricks_ai_gateway":
        chat_databricks = _databricks_class()
        if chat_databricks is not None and endpoint:
            try:
                gateway: BaseChatModel = chat_databricks(
                    model=default_model,
                    api_key=credential,
                    api_base=endpoint,
                    **extra,
                )
            except TypeError:
                gateway = chat_databricks(model=default_model, **extra)
            return gateway
        chat_openai = _openai_class()
        base_url = f"{(endpoint or '').rstrip('/')}/serving-endpoints"
        fallback: BaseChatModel = chat_openai(
            model=model,
            api_key=SecretStr(credential),
            base_url=base_url,
            **extra,
        )
        return fallback
    raise InvalidProviderKindError(f"unknown provider kind {kind!r}")
