"""Credential references shared by every bounded context.

A connection or LLM provider stores a self-describing credential reference.
Besides the ``env:`` and ``file:`` schemes, a local Databricks CLI profile is
addressed as ``profile:<name>``; an empty name means the profile the SDK
resolves by default (``DATABRICKS_CONFIG_PROFILE``, then ``DEFAULT``).
"""

from __future__ import annotations

PROFILE_SCHEME = "profile:"
"""Prefix of a credential reference that names a Databricks CLI profile."""


def profile_reference(ref: str | None) -> str | None:
    """Returns the Databricks CLI profile named by ``ref``, if any.

    Args:
        ref: Credential reference, for example ``profile:team`` or ``env:TOKEN``.

    Returns:
        The profile name, ``""`` when ``ref`` is exactly ``profile:`` (meaning
        the default profile), or ``None`` when ``ref`` is not a profile
        reference.
    """
    if ref is None:
        return None
    text = ref.strip()
    if not text.startswith(PROFILE_SCHEME):
        return None
    return text[len(PROFILE_SCHEME) :].strip()


def profile_credential(name: str) -> str:
    """Returns the credential reference of a Databricks CLI profile.

    Args:
        name: Profile name, or an empty string for the default profile.

    Returns:
        The ``profile:`` reference stored in a connection or provider.
    """
    return f"{PROFILE_SCHEME}{name.strip()}"
