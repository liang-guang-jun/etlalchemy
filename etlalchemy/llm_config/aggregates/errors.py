"""Errors raised by the LLM provider aggregate."""

from __future__ import annotations


class LlmConfigError(Exception):
    """Base class of every error of the LLM provider context."""


class DiscardedError(LlmConfigError, RuntimeError):
    """Raised when a command targets a discarded provider."""


class InvalidProviderNameError(LlmConfigError, ValueError):
    """Raised when a provider name is blank or too long."""


class InvalidProviderKindError(LlmConfigError, ValueError):
    """Raised when a provider kind is unknown."""


class ProviderCredentialError(LlmConfigError, ValueError):
    """Raised when a provider does not carry exactly one credential source."""


class MissingEndpointError(LlmConfigError, ValueError):
    """Raised when a kind that needs an endpoint is created without one."""


class MissingModelError(LlmConfigError, ValueError):
    """Raised when a profile provider does not name the model to run."""


class UnknownProviderError(LlmConfigError):
    """Raised when a provider id does not resolve to a live provider."""


class DuplicateProviderNameError(LlmConfigError):
    """Raised when a provider name is already taken by a live provider."""


class InvalidSharingError(LlmConfigError, ValueError):
    """Raised when a provider cannot be shared the way the caller asked."""


class UnknownShareTargetError(LlmConfigError):
    """Raised when a share targets an unknown user or group."""


class MissingAdapterError(LlmConfigError, ImportError):
    """Raised when the provider package of a kind is not installed."""
