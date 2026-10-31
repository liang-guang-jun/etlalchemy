"""The external database a reflection run reads metadata from."""

from __future__ import annotations

import dataclasses


@dataclasses.dataclass(frozen=True)
class ReflectSource:
    """One external database to reflect tables from.

    ``connection_url`` takes priority: when it is set, the URL is used as is.
    Otherwise ``profile`` selects a Databricks CLI profile. When both are
    ``None`` and ``auto_detect`` is True, the connection is detected in this
    order: the Databricks notebook runtime, the ``DATABRICKS_*`` environment
    variables, then the ``DEFAULT`` profile of ``~/.databrickscfg``.

    A source describes how to connect only; which catalog, schema and tables to
    reflect is passed to the reflector or the reflection call.
    """

    connection_url: str | None = None
    profile: str | None = None
    auto_detect: bool = True


__all__ = ["ReflectSource"]
