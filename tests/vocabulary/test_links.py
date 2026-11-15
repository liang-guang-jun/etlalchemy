"""Tests for the resolution of term links against the catalog read model."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID, uuid4

from etlalchemy.vocabulary.links import resolve_term_links
from etlalchemy.vocabulary.projection.view import TermLinkRow


@dataclass(frozen=True)
class _Named:
    """Row with the attributes link resolution reads."""

    name: str
    catalog_id: UUID | None = None
    schema_id: UUID | None = None
    table_id: UUID | None = None


class _NamedCatalogView:
    """Catalog view that reports a name for every declared object."""

    def __init__(self) -> None:
        """Starts with an empty catalog tree."""
        self.catalogs: dict[UUID, str] = {}
        self.schemas: dict[UUID, str] = {}
        self.tables: dict[UUID, str] = {}
        self.fields: dict[UUID, set[str]] = {}
        self.schema_catalog: dict[UUID, UUID] = {}
        self.table_schema: dict[UUID, UUID] = {}
        self.table_catalog: dict[UUID, UUID] = {}

    async def get_catalog(self, catalog_id: UUID) -> _Named | None:
        """Returns the catalog row when it exists."""
        name = self.catalogs.get(catalog_id)
        return None if name is None else _Named(name=name, catalog_id=catalog_id)

    async def get_schema(self, schema_id: UUID) -> _Named | None:
        """Returns the schema row when it exists."""
        name = self.schemas.get(schema_id)
        if name is None:
            return None
        return _Named(
            name=name,
            catalog_id=self.schema_catalog.get(schema_id),
            schema_id=schema_id,
        )

    async def get_table(self, table_id: UUID) -> _Named | None:
        """Returns the table row when it exists."""
        name = self.tables.get(table_id)
        if name is None:
            return None
        return _Named(
            name=name,
            catalog_id=self.table_catalog.get(table_id),
            schema_id=self.table_schema.get(table_id),
            table_id=table_id,
        )

    async def list_fields(self, table_id: UUID) -> list[_Named]:
        """Returns the fields declared for the table."""
        return [_Named(name=name) for name in sorted(self.fields.get(table_id, set()))]


async def test_catalog_schema_and_table_links_resolve_to_their_name() -> None:
    """A plain link resolves to the name of its target."""
    catalog = _NamedCatalogView()
    catalog_id, schema_id, table_id = uuid4(), uuid4(), uuid4()
    catalog.catalogs[catalog_id] = "analytics"
    catalog.schemas[schema_id] = "sales"
    catalog.tables[table_id] = "orders"

    resolved = await resolve_term_links(
        catalog,
        [
            TermLinkRow(target_id=catalog_id, target_kind="catalog", field_name=""),
            TermLinkRow(target_id=schema_id, target_kind="schema", field_name=""),
            TermLinkRow(target_id=table_id, target_kind="table", field_name=""),
        ],
    )

    assert [(link.status, link.target_name) for link in resolved] == [
        ("resolved", "analytics"),
        ("resolved", "sales"),
        ("resolved", "orders"),
    ]


async def test_a_field_link_resolves_to_the_qualified_field_name() -> None:
    """A field link is named after its table and field."""
    catalog = _NamedCatalogView()
    table_id = uuid4()
    catalog.tables[table_id] = "orders"
    catalog.fields[table_id] = {"total"}

    resolved = await resolve_term_links(
        catalog,
        [TermLinkRow(target_id=table_id, target_kind="field", field_name="total")],
    )

    assert resolved[0].status == "resolved"
    assert resolved[0].target_name == "orders.total"


async def test_a_field_link_to_a_missing_field_is_dangling() -> None:
    """A field that is gone from an existing table dangles."""
    catalog = _NamedCatalogView()
    table_id = uuid4()
    catalog.tables[table_id] = "orders"
    catalog.fields[table_id] = {"other"}

    resolved = await resolve_term_links(
        catalog,
        [TermLinkRow(target_id=table_id, target_kind="field", field_name="total")],
    )

    assert resolved[0].status == "dangling"
    assert resolved[0].target_name is None


async def test_resolved_links_carry_the_ids_needed_for_navigation() -> None:
    """Resolved links expose the catalog, schema and table ids of their target."""
    catalog = _NamedCatalogView()
    catalog_id, schema_id, table_id = uuid4(), uuid4(), uuid4()
    catalog.catalogs[catalog_id] = "analytics"
    catalog.schemas[schema_id] = "sales"
    catalog.schema_catalog[schema_id] = catalog_id
    catalog.tables[table_id] = "orders"
    catalog.table_schema[table_id] = schema_id
    catalog.table_catalog[table_id] = catalog_id
    catalog.fields[table_id] = {"total"}

    resolved = await resolve_term_links(
        catalog,
        [
            TermLinkRow(target_id=catalog_id, target_kind="catalog", field_name=""),
            TermLinkRow(target_id=schema_id, target_kind="schema", field_name=""),
            TermLinkRow(target_id=table_id, target_kind="table", field_name=""),
            TermLinkRow(target_id=table_id, target_kind="field", field_name="total"),
        ],
    )

    assert [(row.catalog_id, row.schema_id, row.table_id) for row in resolved] == [
        (catalog_id, None, None),
        (catalog_id, schema_id, None),
        (catalog_id, schema_id, table_id),
        (catalog_id, schema_id, table_id),
    ]


async def test_a_link_to_a_missing_target_is_dangling() -> None:
    """Every kind dangles when its target no longer exists."""
    catalog = _NamedCatalogView()
    missing = uuid4()

    resolved = await resolve_term_links(
        catalog,
        [
            TermLinkRow(target_id=missing, target_kind="catalog", field_name=""),
            TermLinkRow(target_id=missing, target_kind="schema", field_name=""),
            TermLinkRow(target_id=missing, target_kind="table", field_name=""),
            TermLinkRow(target_id=missing, target_kind="field", field_name="total"),
        ],
    )

    assert [link.status for link in resolved] == ["dangling"] * 4


async def test_an_unknown_target_kind_is_dangling() -> None:
    """A kind this resolver does not know cannot be resolved."""
    catalog = _NamedCatalogView()

    resolved = await resolve_term_links(
        catalog,
        [TermLinkRow(target_id=uuid4(), target_kind="view", field_name="")],
    )

    assert resolved[0].status == "dangling"


async def test_resolution_keeps_the_link_identity_and_leaves_the_input_alone() -> None:
    """Resolving returns new rows and keeps the identifying fields."""
    catalog = _NamedCatalogView()
    table_id = uuid4()
    catalog.tables[table_id] = "orders"
    link = TermLinkRow(target_id=table_id, target_kind="table", field_name="")

    resolved = await resolve_term_links(catalog, [link])

    assert resolved[0].target_id == table_id
    assert resolved[0].target_kind == "table"
    assert resolved[0].field_name == ""
    assert link.status is None
    assert link.target_name is None
