"""Tests for drawing a diagram as a notebook fragment."""

from __future__ import annotations

import re
import sys
from typing import cast

import pytest
from diagram_fixtures import make_entity, make_model, model_of, relationship
from etlalchemy.diagram.theme import Theme
from etlalchemy.semantic import FilterDirection, Integer, SemanticModel


def test_to_html_is_light_unless_asked_otherwise() -> None:
    html = make_model().diagram().to_html()

    assert "--ea-surface:#ffffff" in html
    assert "#0d1117" not in html


def test_to_html_can_be_asked_for_the_dark_palette() -> None:
    html = make_model().diagram().to_html(theme="dark")

    assert "--ea-surface:#0d1117" in html
    assert "#ffffff" not in html


def test_to_html_follows_the_reader_when_asked_to() -> None:
    html = make_model().diagram().to_html(theme="auto")

    assert "--ea-surface:#ffffff" in html
    assert "--ea-surface:#0d1117" in html
    assert "prefers-color-scheme" in html


def test_to_html_rejects_a_theme_it_does_not_know() -> None:
    with pytest.raises(ValueError, match="Unknown theme"):
        make_model().diagram().to_html(theme=cast(Theme, "sepia"))


def test_to_html_draws_every_box_and_its_columns() -> None:
    html = make_model().diagram().to_html()

    assert "<svg" in html
    assert "Customer" in html
    assert "Order" in html
    assert "customer_id" in html
    assert "decimal(10,2)" in html


def test_to_html_draws_the_columns_of_every_box_of_a_row() -> None:
    left = make_entity("Left", [("left_id", Integer())])
    right = make_entity("Right", [("right_id", Integer())])

    html = model_of({"Left": left, "Right": right}).diagram().to_html()

    assert "left_id" in html
    assert "right_id" in html


def test_to_html_draws_the_join_and_its_cardinality() -> None:
    html = make_model().diagram().to_html()

    assert "1:N" in html
    assert "marker-end" in html


def test_to_html_draws_one_arrowhead_for_a_one_way_relationship() -> None:
    html = make_model().diagram().to_html()

    assert "marker-start" not in html


def test_to_html_draws_two_arrowheads_for_a_relationship_read_both_ways() -> None:
    customer = make_entity("Customer", [("id", Integer())])
    order = make_entity("Order", [("customer_id", Integer())])
    model = model_of(
        {"Customer": customer, "Order": order},
        [
            relationship(
                "customer_orders",
                customer,
                "id",
                order,
                "customer_id",
                filter_direction=FilterDirection.BOTH,
            )
        ],
    )

    html = model.diagram().to_html()

    assert "marker-start" in html


def test_to_html_joins_two_boxes_without_wagging_between_them() -> None:
    html = make_model().diagram().to_html()
    path = next(
        found for found in re.findall(r'<path d="(M [^"]+)"', html) if " C " in found
    )
    numbers = [float(number) for number in re.findall(r"-?\d+\.\d+", path)]

    start_y, first_y, second_y, end_y = numbers[1], numbers[3], numbers[5], numbers[7]

    assert start_y <= first_y <= second_y <= end_y


def test_to_html_marks_keys_and_joined_columns() -> None:
    html = make_model().diagram().to_html()

    assert "primary key" in html
    assert "joined by a relationship" in html


def test_to_html_puts_the_key_beside_the_column_name() -> None:
    html = make_model().diagram().to_html()

    assert html.index(">id<") < html.index('class="ea-key"')


def test_to_html_puts_the_link_before_the_column_name() -> None:
    html = make_model().diagram().to_html()

    assert html.index('class="ea-link"') < html.index(">id<")


def test_to_html_draws_the_table_an_entity_stands_for() -> None:
    html = make_model().diagram().to_html()

    assert "public.customer" in html


def test_to_html_draws_a_title_when_asked_for_one() -> None:
    html = make_model().diagram().to_html(title="Sales")

    assert ">Sales<" in html


def test_to_html_leaves_the_columns_out_when_asked_to() -> None:
    html = make_model().diagram().to_html(show_columns=False)

    assert "Customer" in html
    assert "customer_id" not in html


def test_to_html_scopes_its_styles_to_the_diagram() -> None:
    html = make_model().diagram().to_html()
    first = html.split('id="', 1)[1].split('"', 1)[0]

    assert "<style>" in html
    assert f"#{first}" in html


def test_to_html_escapes_names_it_draws() -> None:
    entity = make_entity("<script>alert(1)</script>", [("id", Integer())])

    html = model_of({entity.alias: entity}).diagram().to_html()

    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_to_html_is_the_same_every_time_it_is_asked() -> None:
    diagram = make_model().diagram()

    assert diagram.to_html() == diagram.to_html()


def test_to_html_draws_every_direction_differently() -> None:
    diagram = make_model().diagram()

    assert diagram.to_html(direction="vertical") != diagram.to_html(
        direction="horizontal"
    )


def test_to_html_says_so_when_there_is_nothing_to_draw() -> None:
    html = SemanticModel(name="Empty").diagram().to_html()

    assert "No entity to draw" in html


def test_repr_html_draws_the_canvas() -> None:
    diagram = make_model().diagram()
    shown = diagram._repr_html_()

    assert "<iframe" in shown
    assert "react-flow__node" in shown
    assert shown != diagram.to_html()


def test_render_returns_a_display_object() -> None:
    pytest.importorskip("IPython.display")
    diagram = make_model().diagram()

    rendered = diagram.render()
    shown = getattr(rendered, "data", "")

    assert "<iframe" in shown
    assert "srcdoc=" in shown


def test_render_returns_html_when_ipython_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(sys.modules, "IPython.display", None)

    rendered = make_model().diagram().render()

    assert isinstance(rendered, str)
    assert "<svg" in rendered
