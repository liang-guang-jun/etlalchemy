"""Tests for the interactive React Flow picture of a diagram."""

from __future__ import annotations

import json
import re
import sys
from importlib import resources
from typing import Any

import pytest
from diagram_fixtures import make_entity, model_of, relationship
from etlalchemy.diagram.interactive import picture_height
from etlalchemy.semantic import FilterDirection, Integer, SemanticModel, String


def make_model() -> SemanticModel:
    """Build the two-entity model the interactive tests draw."""
    customer = make_entity("Customer", [("id", Integer()), ("name", String())])
    order = make_entity("Order", [("id", Integer()), ("customer_id", Integer())])
    return model_of(
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


def data_of(html: str) -> dict[str, Any]:
    found = re.search(
        r'<script type="application/json" id="etlalchemy-diagram">(.*?)</script>',
        html,
        re.S,
    )
    assert found is not None, "the diagram data was not embedded"
    parsed: dict[str, Any] = json.loads(found.group(1))
    return parsed


def nodes_of(html: str) -> list[dict[str, Any]]:
    nodes: list[dict[str, Any]] = data_of(html)["nodes"]
    return nodes


def edges_of(html: str) -> list[dict[str, Any]]:
    edges: list[dict[str, Any]] = data_of(html)["edges"]
    return edges


def test_interactive_html_is_light_unless_asked_otherwise() -> None:
    html = make_model().diagram().to_interactive_html()

    assert '<html lang="en" data-theme="light">' in html
    assert data_of(html)["theme"] == "light"


def test_interactive_html_can_be_asked_for_the_dark_palette() -> None:
    html = make_model().diagram().to_interactive_html(theme="dark")

    assert '<html lang="en" data-theme="dark">' in html
    assert data_of(html)["theme"] == "dark"


def test_interactive_html_leaves_the_theme_to_the_reader_when_asked() -> None:
    html = make_model().diagram().to_interactive_html(theme="auto")

    assert '<html lang="en">' in html
    assert data_of(html)["theme"] == "auto"


def test_render_passes_the_theme_to_the_still_picture() -> None:
    pytest.importorskip("IPython.display")
    diagram = make_model().diagram()

    rendered = diagram.render(
        interactive=False,
        direction="vertical",
        theme="dark",
    )

    assert getattr(rendered, "data", None) == diagram.to_html(
        direction="vertical",
        theme="dark",
    )


def test_interactive_html_is_a_standalone_document() -> None:
    html = make_model().diagram().to_interactive_html()

    assert html.startswith("<!doctype html>")
    assert 'id="etlalchemy-canvas"' in html


def test_interactive_html_draws_itself_with_no_network() -> None:
    """A notebook draws the page inside a sandbox, where a CDN may be unreachable."""
    html = make_model().diagram().to_interactive_html()

    assert "<script src=" not in html
    assert "<link" not in html
    assert "@import" not in html
    assert "importmap" not in html


def test_interactive_html_carries_the_canvas_it_draws_with() -> None:
    html = make_model().diagram().to_interactive_html()

    assert "react-flow__node" in html
    assert "Auto layout" in html
    assert "Fit view" in html


def test_canvas_source_draws_its_marks_with_lucide() -> None:
    templates = resources.files("etlalchemy.diagram") / "templates"
    source = (templates / "app.js").read_text()

    assert "lucide-react" in source
    assert "KeyRound" in source
    assert "Link2" in source


def test_interactive_templates_ship_with_the_package() -> None:
    templates = resources.files("etlalchemy.diagram") / "templates"

    for name in (
        "document.html",
        "still.html",
        "app.js",
        "canvas.js",
        "flow.css",
        "style.css",
    ):
        assert (templates / name).is_file(), name


def test_interactive_html_refers_to_its_arrowheads_by_id() -> None:
    html = make_model().diagram().to_interactive_html()

    assert '<marker id="ea-arrow"' in html
    assert "url(#ea-arrow" not in html


def test_interactive_html_keeps_its_actions_in_the_controls() -> None:
    html = make_model().diagram().to_interactive_html()

    assert "Auto layout" in html
    assert "Fit view" in html
    assert "ea-group" not in html


def test_picture_height_leaves_room_around_the_picture() -> None:
    diagram = make_model().diagram()
    empty = SemanticModel(name="Empty").diagram()

    assert picture_height(diagram, direction="vertical") >= 420
    assert picture_height(empty, direction="vertical") < picture_height(
        diagram,
        direction="vertical",
    )


def test_interactive_html_carries_the_static_picture_as_a_fallback() -> None:
    html = make_model().diagram().to_interactive_html()

    assert "<svg" in html
    assert "customer_id" in html


def test_interactive_html_embeds_every_box_and_line() -> None:
    html = make_model().diagram().to_interactive_html()

    assert [node["name"] for node in nodes_of(html)] == ["Customer", "Order"]
    assert [edge["name"] for edge in edges_of(html)] == ["customer_orders"]


def test_interactive_html_embeds_the_columns_with_their_marks() -> None:
    html = make_model().diagram().to_interactive_html()
    order = next(node for node in nodes_of(html) if node["name"] == "Order")
    columns = {column["name"]: column for column in order["columns"]}

    assert columns["id"]["pk"] is True
    assert columns["id"]["type"] == "int"
    assert columns["customer_id"]["joined"] is True
    assert order["table"] == "public.order"


def test_interactive_html_embeds_the_columns_each_line_joins() -> None:
    edge = edges_of(make_model().diagram().to_interactive_html())[0]

    assert edge["source_columns"] == ["id"]
    assert edge["target_columns"] == ["customer_id"]
    assert edge["mark"] == "1:N"
    assert edge["both"] is True


def test_interactive_html_embeds_what_the_card_over_a_line_says() -> None:
    edge = edges_of(make_model().diagram().to_interactive_html())[0]

    assert edge["source_name"] == "Customer"
    assert edge["target_name"] == "Order"
    assert edge["priority"] == 0


def css_rule(html: str, selector: str) -> str:
    found = re.search(re.escape(selector) + r"\{([^}]*)\}", html)
    assert found is not None, f"no rule for {selector}"
    return found.group(1)


def test_canvas_drags_the_card_by_its_head_only() -> None:
    html = make_model().diagram().to_interactive_html()

    assert "ea-list nowheel nodrag" in html
    assert "cursor:grab" in css_rule(html, ".ea-head")


def test_canvas_marks_the_column_under_the_pointer() -> None:
    html = make_model().diagram().to_interactive_html()

    assert "height:24px" in css_rule(html, ".ea-row")
    assert "cursor:pointer" in css_rule(html, ".ea-row")
    assert "var(--ea-surface-hover)" in css_rule(html, ".ea-row:hover")


def test_canvas_shows_what_a_line_joins_over_the_line() -> None:
    html = make_model().diagram().to_interactive_html()

    assert "position:absolute" in css_rule(html, ".ea-pop")
    assert "pointer-events:none" in css_rule(html, ".ea-pop")
    assert "priority" in html


def test_canvas_stacks_the_entity_name_over_the_source_name() -> None:
    html = make_model().diagram().to_interactive_html()

    assert "flex-direction:column" in css_rule(html, ".ea-head")
    assert "margin-left:auto" not in css_rule(html, ".ea-table")


def test_canvas_keeps_the_scrollbar_out_of_sight_until_it_scrolls() -> None:
    html = make_model().diagram().to_interactive_html()

    assert "scrollbar-color:transparent" in css_rule(html, ".ea-list")
    assert "ea-list--scrolling" in html
    assert "var(--ea-edge)" in css_rule(html, ".ea-list--scrolling")


def test_interactive_html_routes_a_join_that_spans_a_row_of_its_own() -> None:
    """A join that skips a row is drawn below its box, not across that row."""
    region = make_entity("Region", [("code", String())])
    agent = make_entity("Agent", [("id", Integer()), ("region_code", String())])
    customer = make_entity(
        "Customer",
        [
            ("id", Integer()),
            ("agent_id", Integer()),
            ("region_code", String()),
        ],
    )
    model = model_of(
        {"Region": region, "Agent": agent, "Customer": customer},
        [
            relationship("region_agents", region, "code", agent, "region_code"),
            relationship("agent_customers", agent, "id", customer, "agent_id"),
            relationship("region_customers", region, "code", customer, "region_code"),
        ],
    )
    edges = {
        edge["name"]: edge for edge in edges_of(model.diagram().to_interactive_html())
    }

    assert edges["region_customers"]["step"] == 0.0
    assert edges["region_agents"]["step"] == 0.5


def test_interactive_html_lays_out_from_the_places_it_was_given() -> None:
    """One layout, not two: the canvas reads the places rather than repeating them."""
    html = make_model().diagram().to_interactive_html()

    assert "function layoutOf" not in html
    assert "function depthsOf" not in html


def test_interactive_html_places_the_boxes_where_the_layout_puts_them() -> None:
    html = make_model().diagram().to_interactive_html()
    placed = {node["name"]: node for node in nodes_of(html)}

    assert placed["Customer"]["y"] < placed["Order"]["y"]


def test_interactive_html_follows_the_direction_it_is_asked_for() -> None:
    diagram = make_model().diagram()
    vertical = {node["name"]: node for node in nodes_of(diagram.to_interactive_html())}
    across = {
        node["name"]: node
        for node in nodes_of(diagram.to_interactive_html(direction="horizontal"))
    }

    assert vertical["Customer"]["y"] < vertical["Order"]["y"]
    assert across["Customer"]["x"] < across["Order"]["x"]


def test_interactive_html_draws_the_title_when_asked_for_one() -> None:
    html = make_model().diagram().to_interactive_html(title="Sales")

    assert data_of(html)["title"] == "Sales"


def test_interactive_html_escapes_a_name_that_would_close_the_script() -> None:
    entity = make_entity("</script><img src=x onerror=alert(1)>", [("id", Integer())])

    html = model_of({entity.alias: entity}).diagram().to_interactive_html()

    assert "</script><img" not in html
    assert "\\u003c/script" in html


def test_interactive_html_of_an_empty_model_still_draws_something() -> None:
    html = SemanticModel(name="Empty").diagram().to_interactive_html()

    assert "No entity to draw" in html


def test_render_is_interactive_by_default() -> None:
    pytest.importorskip("IPython.display")
    rendered = make_model().diagram().render()
    shown = getattr(rendered, "data", "")

    assert "<iframe" in shown
    assert "srcdoc=" in shown


def test_render_can_still_draw_the_static_picture() -> None:
    pytest.importorskip("IPython.display")
    diagram = make_model().diagram()

    rendered = diagram.render(interactive=False, direction="vertical")

    assert getattr(rendered, "data", None) == diagram.to_html(direction="vertical")


def test_render_returns_the_document_when_ipython_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(sys.modules, "IPython.display", None)

    rendered = make_model().diagram().render()

    assert isinstance(rendered, str)
    assert rendered.startswith("<!doctype html>")
