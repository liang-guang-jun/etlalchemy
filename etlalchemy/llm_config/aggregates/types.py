"""Value objects and enumerations of the LLM provider context."""

from __future__ import annotations

from typing import Literal, get_args

from etlalchemy.llm_config.aggregates.errors import (
    InvalidProviderKindError,
    InvalidProviderNameError,
    MissingEndpointError,
    ProviderCredentialError,
)
from etlalchemy.shared.credentials import profile_reference
from etlalchemy.shared.utils import PROFILE_KINDS as PROFILE_KINDS

LlmKind = Literal["openai", "databricks_ai_gateway"]
"""Kinds the chat model factory can build."""

DEFAULT_PROVIDER_KINDS: frozenset[str] = frozenset(get_args(LlmKind))
"""Every accepted provider kind."""

KINDS_REQUIRING_ENDPOINT: frozenset[str] = frozenset({"databricks_ai_gateway"})
"""Kinds that cannot be built without an explicit endpoint."""


MAX_PROVIDER_NAME_LENGTH = 64
"""Maximum length of a provider name."""

DefaultScope = Literal["system", "tenant", "user"]
"""Scope a default provider pointer belongs to."""


def validate_name(name: str) -> str:
    """Returns the stripped provider name, rejecting a blank or over-long one.

    Args:
        name: The name to validate.

    Returns:
        The normalised name.

    Raises:
        InvalidProviderNameError: If the name is blank or longer than
            :data:`MAX_PROVIDER_NAME_LENGTH`.
    """
    cleaned = "" if name is None else name.strip()
    if not cleaned:
        msg = "a provider name must not be blank"
        raise InvalidProviderNameError(msg)
    if len(cleaned) > MAX_PROVIDER_NAME_LENGTH:
        msg = f"a provider name must not exceed {MAX_PROVIDER_NAME_LENGTH} characters"
        raise InvalidProviderNameError(msg)
    return cleaned


def validate_kind(kind: str) -> str:
    """Returns the provider kind, rejecting an unknown one.

    Args:
        kind: The kind to validate.

    Returns:
        The validated kind.

    Raises:
        InvalidProviderKindError: If the kind is not one of the accepted kinds.
    """
    if kind not in DEFAULT_PROVIDER_KINDS:
        msg = f"unknown provider kind {kind!r}; expected one of {sorted(DEFAULT_PROVIDER_KINDS)}"
        raise InvalidProviderKindError(msg)
    return kind


def validate_credential(kind: str, credential_ref: str | None, token: str | None) -> None:
    """Rejects a provider that does not carry exactly one usable credential.

    Args:
        kind: Provider kind being validated.
        credential_ref: External secret reference, if any.
        token: Inline secret, if any.

    Raises:
        ProviderCredentialError: If both or neither are given, the inline token
            is blank, or a profile reference targets a kind that cannot use it.
    """
    if (credential_ref is None) == (token is None):
        msg = "exactly one of credential_ref / token is required"
        raise ProviderCredentialError(msg)
    if token is not None and not token.strip():
        msg = "inline token must not be blank"
        raise ProviderCredentialError(msg)
    if profile_reference(credential_ref) is not None and kind not in PROFILE_KINDS:
        msg = f"provider kind {kind!r} does not support a profile credential"
        raise ProviderCredentialError(msg)


def validate_endpoint(
    kind: str,
    endpoint: str | None,
    credential_ref: str | None = None,
) -> str | None:
    """Rejects a kind that needs an endpoint but has none.

    Args:
        kind: Provider kind being validated.
        endpoint: Endpoint as configured, if any.
        credential_ref: Credential reference, which may name a local profile
            that already carries the workspace host.

    Returns:
        The endpoint without surrounding whitespace, or ``None``.

    Raises:
        MissingEndpointError: If the kind requires an endpoint and none is set
            and no profile reference supplies one.
    """
    cleaned = None if endpoint is None else endpoint.strip()
    has_profile = profile_reference(credential_ref) is not None
    if kind in KINDS_REQUIRING_ENDPOINT and not cleaned and not has_profile:
        msg = f"provider kind {kind!r} requires an endpoint"
        raise MissingEndpointError(msg)
    return cleaned
