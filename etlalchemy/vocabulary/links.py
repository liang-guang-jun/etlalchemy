"""Resolution of term links against the catalog read model.

A term link points at a catalog, schema, table or field of another bounded
context, so only a read of the catalog view can tell whether the target still
exists. Every delivery layer resolves links before rendering a term, which is
why this lives in the vocabulary context instead of one of them.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace

from etlalchemy.catalog.projection.view import CatalogView
from etlalchemy.vocabulary.projection.view import TermLinkRow


async def _resolve_link(catalog: CatalogView, link: TermLinkRow) -> TermLinkRow:
    """Resolves one link, filling its name and the ids its page navigates with."""
    if link.target_kind == "catalog":
        catalog_row = await catalog.get_catalog(link.target_id)
        if catalog_row is None:
            return replace(link, status="dangling", target_name=None)
        return replace(
            link,
            status="resolved",
            target_name=catalog_row.name,
            catalog_id=catalog_row.catalog_id,
        )
    if link.target_kind == "schema":
        schema_row = await catalog.get_schema(link.target_id)
        if schema_row is None:
            return replace(link, status="dangling", target_name=None)
        return replace(
            link,
            status="resolved",
            target_name=schema_row.name,
            catalog_id=schema_row.catalog_id,
            schema_id=schema_row.schema_id,
        )
    if link.target_kind == "table":
        table_row = await catalog.get_table(link.target_id)
        if table_row is None:
            return replace(link, status="dangling", target_name=None)
        return replace(
            link,
            status="resolved",
            target_name=table_row.name,
            catalog_id=table_row.catalog_id,
            schema_id=table_row.schema_id,
            table_id=table_row.table_id,
        )
    if link.target_kind == "field":
        table = await catalog.get_table(link.target_id)
        if table is None:
            return replace(link, status="dangling", target_name=None)
        names = {field.name for field in await catalog.list_fields(link.target_id)}
        if link.field_name not in names:
            return replace(link, status="dangling", target_name=None)
        return replace(
            link,
            status="resolved",
            target_name=f"{table.name}.{link.field_name}",
            catalog_id=table.catalog_id,
            schema_id=table.schema_id,
            table_id=table.table_id,
        )
    return replace(link, status="dangling", target_name=None)


async def resolve_term_links(
    catalog: CatalogView,
    links: Sequence[TermLinkRow],
) -> list[TermLinkRow]:
    """Returns the links with ``status``, ``target_name`` and navigation ids filled in."""
    return [await _resolve_link(catalog, link) for link in links]
