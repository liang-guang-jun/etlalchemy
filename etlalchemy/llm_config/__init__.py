"""LLM provider context: configured LLM endpoints the agent can run against."""

from __future__ import annotations

from etlalchemy.llm_config.aggregates.errors import (
    DiscardedError,
    DuplicateProviderNameError,
    InvalidProviderKindError,
    InvalidProviderNameError,
    InvalidSharingError,
    LlmConfigError,
    MissingEndpointError,
    ProviderCredentialError,
    UnknownProviderError,
    UnknownShareTargetError,
)
from etlalchemy.llm_config.aggregates.provider import LlmProvider
from etlalchemy.llm_config.aggregates.types import (
    DEFAULT_PROVIDER_KINDS,
    DefaultScope,
    LlmKind,
)
from etlalchemy.llm_config.application import (
    SYSTEM_USER_ID,
    LlmConfigApplication,
    LlmConfigOptions,
)
from etlalchemy.llm_config.ports.authorization import (
    LlmConfigAuthorizationPort,
    SessionUser,
)
from etlalchemy.llm_config.ports.secrets import ResolvedSecret, SecretsResolver
from etlalchemy.llm_config.projection import (
    LlmConfigEventApplication,
    LlmConfigProjection,
    LlmProviderView,
    ProviderDefaultRow,
    ProviderDetail,
    ProviderRow,
    ProviderShareRow,
    run_llm_config_projection,
)

__all__ = [
    "DEFAULT_PROVIDER_KINDS",
    "SYSTEM_USER_ID",
    "DefaultScope",
    "DiscardedError",
    "DuplicateProviderNameError",
    "InvalidProviderKindError",
    "InvalidProviderNameError",
    "InvalidSharingError",
    "LlmConfigApplication",
    "LlmConfigAuthorizationPort",
    "LlmConfigError",
    "LlmConfigEventApplication",
    "LlmConfigOptions",
    "LlmConfigProjection",
    "LlmKind",
    "LlmProvider",
    "LlmProviderView",
    "MissingEndpointError",
    "ProviderCredentialError",
    "ProviderDefaultRow",
    "ProviderDetail",
    "ProviderRow",
    "ProviderShareRow",
    "ResolvedSecret",
    "SecretsResolver",
    "SessionUser",
    "UnknownProviderError",
    "UnknownShareTargetError",
    "run_llm_config_projection",
]
