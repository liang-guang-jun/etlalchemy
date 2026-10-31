"""Tests for keeping a wide box short by dropping the columns it cannot show."""

from __future__ import annotations

import re

from etlalchemy.diagram.diagram import (
    Diagram,
    DiagramColumn,
    DiagramEdge,
    DiagramNode,
)
from etlalchemy.diagram.interactive import picture_height
from etlalchemy.diagram.render import box_size

_HEADER = 34.0
_TABLE_LINE = 12.0
_ROW = 24.0
_FOOTER = 8.0


def _node(name: str, count: int, entity: str, *, keys: bool = True) -> DiagramNode:
    """Return a box with ``count`` columns and its key and join columns."""
    columns = tuple(
        DiagramColumn(
            name=f"column_{index}",
            data_type="string",
            is_primary_key=keys and index == 100,
            is_joined=keys and index == 5,
        )
        for index in range(count)
    )
    return DiagramNode(
        entity_id=entity,
        name=name,
        columns=columns,
        table=f"main.default.{name}",
    )


def _diagram() -> Diagram:
    """Return the reported case: a 140-column dimension joined to a 72-column fact."""
    return Diagram(
        nodes=(
            _node("dim_agent", 140, "dim"),
            _node("fact_transaction", 72, "fact"),
        ),
        edges=(
            DiagramEdge(
                relationship_id="rel",
                name="rel",
                source_entity_id="dim",
                target_entity_id="fact",
            ),
        ),
    )


def test_a_trimmed_box_keeps_the_budget_and_counts_the_rest() -> None:
    """A 140-column box keeps 20 columns and says how many it dropped."""
    node = _diagram().trimmed(20).nodes[0]

    assert len(node.columns) == 20
    assert node.hidden_columns == 120


def test_trimming_keeps_key_and_joined_columns_in_their_original_order() -> None:
    """Columns the picture is read for survive, and nothing is reordered."""
    node = _diagram().trimmed(20).nodes[0]

    names = [column.name for column in node.columns]

    assert "column_5" in names  # joined
    assert "column_100" in names  # primary key, far down the table
    assert names == sorted(names, key=lambda name: int(name.rsplit("_", 1)[1]))


def test_a_box_never_shrinks_below_its_key_columns() -> None:
    """More mandatory columns than the budget keeps every mandatory column."""
    node = DiagramNode(
        entity_id="wide",
        name="wide",
        columns=tuple(
            DiagramColumn(name=f"k{index}", is_primary_key=True) for index in range(5)
        ),
    )

    trimmed = Diagram(nodes=(node,)).trimmed(2).nodes[0]

    assert [column.name for column in trimmed.columns] == [
        "k0",
        "k1",
        "k2",
        "k3",
        "k4",
    ]
    assert trimmed.hidden_columns == 0


def test_the_hidden_row_counts_in_the_box_height() -> None:
    """The ``- +N more columns`` row is a row of the box."""
    node = _diagram().trimmed(20).nodes[0]

    _, height = box_size(node, True)

    assert height == _HEADER + _TABLE_LINE + 21 * _ROW + _FOOTER


def test_a_diagram_within_the_budget_is_returned_unchanged() -> None:
    """Trimming is not a copy when there is nothing to hide."""
    diagram = Diagram(nodes=(_node("dim_agent", 6, "dim"),))

    assert diagram.trimmed(6) is diagram
    assert diagram.trimmed(None) is diagram


def test_a_narrow_diagram_renders_exactly_as_it_did_before() -> None:
    """The column budget changes nothing when no box reaches it."""
    diagram = Diagram(nodes=(_node("dim_agent", 6, "dim"),))

    assert diagram.to_html() == diagram.to_html(max_columns=None)
    assert diagram.to_interactive_html() == diagram.to_interactive_html(
        max_columns=None
    )


def test_the_still_picture_names_the_hidden_columns() -> None:
    """The SVG carries the row that says how much is not drawn."""
    html = _diagram().to_html()

    assert "- +134 more columns" in html
    assert "- +66 more columns" in html


def test_the_canvas_data_carries_the_hidden_count() -> None:
    """The canvas is told how many columns it is not drawing."""
    document = _diagram().to_interactive_html()

    hidden = re.findall(r'"hiddenColumns": (\d+)', document)

    assert hidden == ["134", "66"]


def test_picture_height_uses_an_explicit_height() -> None:
    """A caller that knows the frame height gets exactly that."""
    assert picture_height(_diagram(), height=300) == 300


def test_picture_height_is_bounded_by_max_height() -> None:
    """The frame asks for what the picture needs, within the page bounds."""
    diagram = _diagram()

    assert picture_height(diagram) == 420
    assert picture_height(diagram, max_columns=None) == 920
    assert picture_height(diagram, max_columns=None, max_height=20_000) > 920
