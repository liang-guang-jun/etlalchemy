"""Draw a diagram as an interactive canvas.

The static picture (:mod:`etlalchemy.diagram.render`) says what the model is;
this one lets a reader ask about it. It is the same picture the vizetl client
draws (``pages/semantic-model/ui/DiagramCanvas.tsx``), built on the same
library — React Flow — so a reader who has used the canvas in the product
already knows what to do here:

* a box can be dragged;
* the wheel zooms and the corner controls fit the picture to the view;
* a smaller copy of the whole picture sits in a corner for a model too wide to
  see at once;
* pointing at a line lifts the columns that line joins to the head of both
  boxes and marks them, which is what says what is joined to what without
  writing it on the line;
* a button lays every box out again along the joins.

The places themselves are not worked out here: they come from
:mod:`etlalchemy.diagram.layout`, which lays the picture out along its joins
and keeps each join in the room between two rows, so that a line is not drawn
across a box. The page is told where every box stands and how far along a line
steps across, and drawing it again is reading those places once more.

The page is one HTML document with no build step at read time: React, React
Flow, the icons and the application are bundled into one script that ships in
this package, and the stylesheet ships beside it, so the page is drawn with no
network at all — which is what a notebook output, run inside a sandbox, often
has. The front end's source lives in ``templates/app.js``; ``tools/vendor_canvas.py``
builds the bundle from it. This module only says what to draw: the entities, the
columns, where they stand, and the palette. The static picture is drawn into the
document first, and stays there until the canvas is up, so a reader whose
browser cannot run the script still sees the diagram.
"""

from __future__ import annotations

import json
from functools import cache
from importlib import resources
from typing import Any

from jinja2 import Environment, PackageLoader, StrictUndefined

from etlalchemy.diagram.diagram import Diagram, DiagramNode
from etlalchemy.diagram.layout import (
    Join,
    LayoutDirection,
    Standing,
    layout_of,
)
from etlalchemy.diagram.render import MARKS, box_size, render_html
from etlalchemy.diagram.theme import (
    DARK_PALETTE,
    PALETTE,
    Theme,
    checked,
    variables,
)
from etlalchemy.semantic.relationship import FilterDirection

# The templates are part of the package, so they are found the way the rest of
# the package is found rather than by a path written down here.
_ENV = Environment(
    loader=PackageLoader("etlalchemy.diagram", "templates"),
    autoescape=False,
    trim_blocks=True,
    lstrip_blocks=True,
    keep_trailing_newline=True,
    undefined=StrictUndefined,
)


@cache
def _asset(name: str) -> str:
    """Return one file shipped beside the templates, read once."""
    return (
        resources.files("etlalchemy.diagram")
        .joinpath("templates")
        .joinpath(name)
        .read_text(encoding="utf-8")
    )


def interactive_html(
    diagram: Diagram,
    *,
    direction: LayoutDirection = "vertical",
    title: str | None = None,
    show_columns: bool = True,
    theme: Theme = "light",
) -> str:
    """Return the diagram as a self-contained interactive document.

    Args:
        diagram: The diagram to draw.
        direction: ``"vertical"`` to stack relationship depth downwards,
            ``"horizontal"`` to stack it rightwards.
        title: Heading drawn above the picture, or ``None`` for none.
        show_columns: Whether to draw the columns of each entity.
        theme: ``"light"`` or ``"dark"`` to draw in that palette, or
            ``"auto"`` to follow the screen the picture is read on.

    Returns:
        One HTML document holding the canvas, the data it draws, and the static
        picture as the fallback for a reader whose browser cannot reach the
        library.

    Raises:
        ValueError: If ``theme`` names no palette.
    """
    palette = checked(theme)
    fallback = render_html(
        diagram,
        direction=direction,
        title=title,
        show_columns=show_columns,
        theme=palette,
    )
    name = "Semantic model diagram" if title is None else title
    page: dict[str, Any] = {
        "title": _escape(name),
        "fallback": fallback,
        "theme": palette,
        "light": variables(PALETTE),
        "dark": variables(DARK_PALETTE),
    }

    if not diagram.nodes:
        return _ENV.get_template("still.html").render(page)

    return _ENV.get_template("document.html").render(
        page,
        flow_css=_asset("flow.css"),
        canvas_js=_asset("canvas.js"),
        data=_data(diagram, direction, show_columns, title, palette),
    )


def picture_height(
    diagram: Diagram,
    *,
    direction: LayoutDirection = "vertical",
    show_columns: bool = True,
    title: str | None = None,
) -> int:
    """Return how tall a frame holding the canvas should be, in pixels.

    The height is what the laid-out picture needs, so that a diagram is drawn
    whole rather than scrolled to inside its own frame, within the bounds a
    notebook page reads well at. The room left under the picture is what the
    corner controls and the minimap stand in.
    """
    placed = _places(diagram, direction, show_columns)
    if not placed:
        return 260

    bottom = max(spot["y"] + spot["height"] for spot in placed)
    height = bottom + 2 * 16 + (34 if title else 0) + 64

    return int(min(max(height, 420), 920))


def _data(
    diagram: Diagram,
    direction: LayoutDirection,
    show_columns: bool,
    title: str | None,
    theme: Theme,
) -> str:
    """Return the diagram as the JSON the canvas is drawn from."""
    placed = _places(diagram, direction, show_columns)
    spots = {spot["id"]: spot for spot in placed}
    names = {node.entity_id: node.name for node in diagram.nodes}
    ranks = _ranks(placed, direction)

    payload: dict[str, Any] = {
        "title": title,
        "theme": theme,
        "direction": direction,
        "show_columns": show_columns,
        "nodes": [
            {
                "id": node.entity_id,
                "name": node.name,
                "table": node.table,
                "width": spots[node.entity_id]["width"],
                "height": spots[node.entity_id]["height"],
                "x": spots[node.entity_id]["x"],
                "y": spots[node.entity_id]["y"],
                "columns": [
                    {
                        "name": column.name,
                        "type": column.data_type,
                        "pk": column.is_primary_key,
                        "joined": column.is_joined,
                    }
                    for column in (node.columns if show_columns else ())
                ],
            }
            for node in diagram.nodes
        ],
        "edges": [
            {
                "id": edge.relationship_id,
                "name": edge.name,
                "source": edge.source_entity_id,
                "target": edge.target_entity_id,
                "source_name": names[edge.source_entity_id],
                "target_name": names[edge.target_entity_id],
                "source_columns": list(edge.source_columns),
                "target_columns": list(edge.target_columns),
                "mark": MARKS[edge.cardinality],
                "both": edge.direction is FilterDirection.BOTH,
                "priority": edge.priority,
                # Where the line steps across, as a share of the way from the
                # box it leaves to the box it reaches. A line between two rows
                # that touch steps in the room between them; a line that skips
                # a row steps as soon as it leaves its box, so the row it
                # passes is not drawn on top of it.
                "step": (
                    0.0
                    if ranks[edge.target_entity_id] - ranks[edge.source_entity_id] > 1
                    else 0.5
                ),
            }
            for edge in diagram.edges
        ],
    }

    # A name is data, not markup, so every `<` is written as an escape: what a
    # reader names an entity cannot close the element that carries it.
    return json.dumps(payload).replace("<", "\\u003c")


def _places(
    diagram: Diagram,
    direction: LayoutDirection,
    show_columns: bool,
) -> list[dict[str, Any]]:
    """Return where each box stands and how big it is drawn."""
    sizes = {node.entity_id: box_size(node, show_columns) for node in diagram.nodes}
    spots = layout_of(
        [_standing(node, sizes) for node in diagram.nodes],
        [Join(edge.source_entity_id, edge.target_entity_id) for edge in diagram.edges],
        direction,
    )

    return [
        {
            "id": spot.entity_id,
            "x": spot.x,
            "y": spot.y,
            "width": sizes[spot.entity_id][0],
            "height": sizes[spot.entity_id][1],
        }
        for spot in spots
    ]


def _standing(
    node: DiagramNode,
    sizes: dict[str, tuple[float, float]],
) -> Standing:
    """Return one box as the layout is told about it."""
    width, height = sizes[node.entity_id]
    return Standing(node.entity_id, width, height)


def _ranks(placed: list[dict[str, Any]], direction: LayoutDirection) -> dict[str, int]:
    """Return which row (or column) of the picture each box stands in.

    The boxes are laid out in rows, so the row a box stands in is counted from
    the first one: two boxes in rows one apart are drawn with the room between
    their rows, and a line between them needs no more room than that.
    """
    key = "y" if direction == "vertical" else "x"
    rows = sorted({spot[key] for spot in placed})
    order = {row: index for index, row in enumerate(rows)}

    return {spot["id"]: order[spot[key]] for spot in placed}


def _escape(text: str) -> str:
    """Return text that can stand inside an HTML element."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
