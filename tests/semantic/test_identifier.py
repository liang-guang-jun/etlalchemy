"""Tests for qualified relation names and the Rowset name they feed."""

from __future__ import annotations

from etlalchemy.semantic import Materialization, QualifiedName, Rowset


def test_a_bare_name_renders_as_itself() -> None:
    """A name without scope is written as is."""
    assert QualifiedName("orders").to_sql() == "orders"


def test_a_schema_is_prefixed() -> None:
    """A schema is written before the name."""
    assert QualifiedName("orders", schema="sales").to_sql() == "sales.orders"


def test_a_catalog_comes_first() -> None:
    """A catalog is written before the schema."""
    name = QualifiedName("orders", schema="sales", catalog="main")

    assert name.to_sql() == "main.sales.orders"


def test_str_renders_the_dotted_name() -> None:
    """``str`` matches the SQL rendering, so f-strings stay readable."""
    assert str(QualifiedName("orders", schema="sales")) == "sales.orders"


def test_a_rowset_wraps_a_bare_string() -> None:
    """A string name is accepted and wrapped in a bare QualifiedName."""
    rowset = Rowset(name="orders", kind=Materialization.TABLE)

    assert rowset.name == QualifiedName("orders")
    assert rowset.sql_name == "orders"


def test_a_rowset_keeps_a_qualified_name() -> None:
    """A QualifiedName is kept as is and renders its full scope."""
    name = QualifiedName("orders", schema="sales", catalog="main")

    rowset = Rowset(name=name, kind=Materialization.TABLE)

    assert rowset.name is name
    assert rowset.sql_name == "main.sales.orders"
