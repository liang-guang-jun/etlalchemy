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

    ``table_names`` selects a subset of the tables in ``schema``; an empty
    tuple reflects every table of the schema.
    """

    connection_url: str | None = None
    schema: str | None = None
    table_names: tuple[str, ...] = ()
    profile: str | None = None
    auto_detect: bool = True


__all__ = ["ReflectSource"]
