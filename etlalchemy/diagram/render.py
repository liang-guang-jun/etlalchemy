"""Draw a diagram as a fragment a notebook displays.

The picture is a self-contained HTML fragment: a scoped stylesheet, and an SVG
that holds every box and every line at the place the layout gives it. Nothing
is fetched and nothing is scripted, so the fragment draws the same in a
notebook, in a served page, or pasted into a document, and it follows the
reader's theme through the same two palettes the client's own canvas uses.

The look follows the semantic-model canvas of the vizetl client
(``pages/semantic-model/ui/DiagramCanvas.tsx``): a box is a card whose head is
the entity's name and table, whose rows are its columns with the key that
reads the table and the link a relationship joins, and whose lines carry the
cardinality they are read with — one arrowhead for a relationship read one way,
two for one read both ways.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from html import escape

from etlalchemy.diagram.diagram import (
    Diagram,
    DiagramColumn,
    DiagramEdge,
    DiagramNode,
)
from etlalchemy.diagram.layout import (
    Join,
    LayoutDirection,
    Standing,
    layout_of,
)
from etlalchemy.diagram.theme import (
    DARK_PALETTE,
    PALETTE,
    Theme,
    checked,
    variables,
)
from etlalchemy.semantic.relationship import Cardinality, FilterDirection

# What each cardinality is drawn as, in the marks a reader of a schema knows.
MARKS: dict[Cardinality, str] = {
    Cardinality.ONE_TO_ONE: "1:1",
    Cardinality.ONE_TO_MANY: "1:N",
    Cardinality.MANY_TO_MANY: "N:N",
}

# How big a box is drawn. The width is the smallest that holds a name and a
# type, and it grows with what it has to hold up to the widest it may get.
_MIN_WIDTH = 240.0
_MAX_WIDTH = 380.0
_PAD_X = 12.0
_ROW = 24.0
_HEADER = 34.0
_TABLE_LINE = 12.0
_FOOTER = 8.0
_ICONS = 24.0
_TYPE_GAP = 12.0
_KEY_ROOM = 10.0
_KEY_GAP = 5.0

# How the text is sized, and about how wide a character is at that size.
_NAME_SIZE = 13.0
_TABLE_SIZE = 10.5
_COLUMN_SIZE = 12.0
_TYPE_SIZE = 11.0
_CHAR = 0.58

# What is left around the picture so that nothing is drawn on the edge of it.
_CANVAS_PAD = 16.0

# A line bends at least this much, so that two boxes in one row are still
# joined by a curve rather than by a line drawn through them.
_MIN_BEND = 40.0

# How far an arrowhead reaches back from the point it is drawn at. A line read
# both ways starts this far from the box it leaves, so that the arrowhead at
# that end stands against the box rather than under it.
_ARROW_REACH = 10.0


@dataclass(frozen=True, slots=True)
class _Rect:
    """A box as it is drawn: where its top-left corner stands, and its size."""

    x: float
    y: float
    width: float
    height: float


def render_html(
    diagram: Diagram,
    *,
    direction: LayoutDirection = "horizontal",
    title: str | None = None,
    show_columns: bool = True,
    max_columns: int | None = 6,
    theme: Theme = "light",
) -> str:
    """Return the diagram as a self-contained HTML fragment.

    Args:
        diagram: The diagram to draw.
        direction: ``"vertical"`` to stack relationship depth downwards,
            ``"horizontal"`` to stack it rightwards.
        title: Heading drawn above the picture, or ``None`` for none.
        show_columns: Whether to draw the columns of each entity.
        max_columns: Columns drawn per box, or ``None`` for every column.
        theme: ``"light"`` or ``"dark"`` to draw in that palette, or
            ``"auto"`` to follow the screen the picture is read on.

    Returns:
        The fragment, whose stylesheet is scoped to the diagram so that it can
        stand beside any other markup.

    Raises:
        ValueError: If ``theme`` names no palette.
    """
    palette = checked(theme)
    uid = f"ea-{digest(diagram)}"
    heading = "" if title is None else f'<div class="ea-title">{escape(title)}</div>'

    if not diagram.nodes:
        return (
            f'<div id="{uid}" class="etlalchemy-diagram">'
            f"<style>{_style(uid, palette)}</style>"
            f"{heading}"
            '<p class="ea-empty">No entity to draw.</p>'
            "</div>"
        )

    picture = render_svg(
        diagram,
        direction=direction,
        show_columns=show_columns,
        max_columns=max_columns,
        uid=uid,
    )

    return (
        f'<div id="{uid}" class="etlalchemy-diagram">'
        f"<style>{_style(uid, palette)}</style>"
        f"{heading}"
        f"{picture}"
        "</div>"
    )


def digest(diagram: Diagram) -> str:
    """Return a stable identity for the diagram's markup.

    It names the stylesheet and the arrowheads, so it has to be the same every
    time the same diagram is drawn — otherwise two draws could be told apart
    only by names that mean nothing — and different for a diagram drawn of
    something else.
    """
    key = "|".join(node.entity_id for node in diagram.nodes)
    key += "#" + "|".join(edge.relationship_id for edge in diagram.edges)
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:10]


def render_svg(
    diagram: Diagram,
    *,
    direction: LayoutDirection = "horizontal",
    show_columns: bool = True,
    max_columns: int | None = 6,
    uid: str = "ea",
) -> str:
    """Return the diagram as one SVG picture.

    The picture is laid out, drawn, and sized in one pass, so it can be handed
    to anything that takes markup: a stylesheet-scoped fragment, the fallback
    of an interactive canvas, or a document of the reader's own.

    Args:
        diagram: The diagram to draw.
        direction: ``"vertical"`` to stack relationship depth downwards,
            ``"horizontal"`` to stack it rightwards.
        show_columns: Whether to draw the columns of each entity.
        max_columns: Columns drawn per box, or ``None`` for every column.
            Primary-key and joined columns are always drawn.
        uid: Prefix for the names the picture gives its arrowheads.

    Returns:
        The ``<svg>`` element, without a stylesheet of its own.
    """
    diagram = diagram.trimmed(max_columns)
    sizes = {node.entity_id: box_size(node, show_columns) for node in diagram.nodes}
    spots = layout_of(
        [Standing(node.entity_id, *sizes[node.entity_id]) for node in diagram.nodes],
        [Join(edge.source_entity_id, edge.target_entity_id) for edge in diagram.edges],
        direction,
    )
    boxes = {
        spot.entity_id: _Rect(
            spot.x,
            spot.y,
            *sizes[spot.entity_id],
        )
        for spot in spots
    }

    if not boxes:
        return ""

    parts = [
        _node_markup(node, boxes[node.entity_id], show_columns)
        for node in diagram.nodes
    ]
    parts.extend(_edge_markup(edge, boxes, direction, uid) for edge in diagram.edges)

    width = max(box.x + box.width for box in boxes.values())
    height = max(box.y + box.height for box in boxes.values())
    body = "".join(part for part in parts if part)

    label = escape(f"Diagram of {len(diagram.nodes)} entities")

    return (
        '<svg xmlns="http://www.w3.org/2000/svg" '
        f'viewBox="0 0 {width + 2 * _CANVAS_PAD:.0f} '
        f'{height + 2 * _CANVAS_PAD:.0f}" '
        f'role="img" aria-label="{label}">'
        f"<defs>{_arrowhead(uid)}</defs>"
        f'<g transform="translate({_CANVAS_PAD:.0f} {_CANVAS_PAD:.0f})">'
        f"{body}"
        "</g></svg>"
    )


def box_size(node: DiagramNode, show_columns: bool) -> tuple[float, float]:
    """Return the size a box is drawn at, which is what it has to hold."""
    header = _HEADER + (_TABLE_LINE if node.table else 0.0)
    rows = max(1, len(node.columns)) if show_columns else 0
    if show_columns and node.hidden_columns:
        rows += 1

    widest = _text_width(node.name, _NAME_SIZE)
    if node.table:
        widest = max(widest, _text_width(node.table, _TABLE_SIZE))
    if show_columns:
        for column in node.columns:
            widest = max(
                widest,
                _ICONS
                + _text_width(column.name, _COLUMN_SIZE)
                + _TYPE_GAP
                + _text_width(column.data_type or "", _TYPE_SIZE),
            )

    width = min(_MAX_WIDTH, max(_MIN_WIDTH, widest + 2 * _PAD_X))
    height = header + rows * _ROW + _FOOTER

    return width, height


def _node_markup(node: DiagramNode, box: _Rect, show_columns: bool) -> str:
    """Return the card a box is drawn as, with its columns a row at a time."""
    header = _HEADER + (_TABLE_LINE if node.table else 0.0)
    parts = [
        "<g>",
        f'<rect x="{box.x:.1f}" y="{box.y:.1f}" width="{box.width:.1f}" '
        f'height="{box.height:.1f}" rx="6" fill="var(--ea-surface-raised)" '
        'stroke="var(--ea-line)"/>',
        _text(
            node.name,
            x=box.x + _PAD_X,
            y=box.y + 21,
            size=_NAME_SIZE,
            fill="var(--ea-ink)",
            limit=box.width - 2 * _PAD_X,
            weight="600",
        ),
    ]

    if node.table:
        parts.append(
            _text(
                node.table,
                x=box.x + _PAD_X,
                y=box.y + 33,
                size=_TABLE_SIZE,
                fill="var(--ea-muted)",
                limit=box.width - 2 * _PAD_X,
            )
        )

    parts.append(
        f'<line x1="{box.x:.1f}" y1="{box.y + header:.1f}" '
        f'x2="{box.x + box.width:.1f}" y2="{box.y + header:.1f}" '
        'stroke="var(--ea-line)"/>'
    )

    if show_columns and not node.columns:
        parts.append(
            _text(
                "No column",
                x=box.x + _PAD_X,
                y=box.y + header + 14,
                size=_COLUMN_SIZE,
                fill="var(--ea-muted)",
                limit=box.width - 2 * _PAD_X,
            )
        )

    for index, column in enumerate(node.columns if show_columns else ()):
        parts.append(
            _column_markup(
                column,
                x=box.x,
                top=box.y + header + index * _ROW,
                width=box.width,
            )
        )

    if show_columns and node.hidden_columns:
        parts.append(
            _text(
                f"- +{node.hidden_columns} more columns",
                x=box.x + _PAD_X,
                y=box.y + header + len(node.columns) * _ROW + 16,
                size=_COLUMN_SIZE,
                fill="var(--ea-muted)",
                limit=box.width - 2 * _PAD_X,
            )
        )

    parts.append("</g>")
    return "".join(parts)


def _column_markup(column: DiagramColumn, x: float, top: float, width: float) -> str:
    """Return one row of a card: what the column is, and what it holds.

    The line a relationship joins stands at the head of the row, where a reader
    scanning for what the picture is about looks first; the key a table is read
    by stands beside the name, because the name is what is being read and the
    key is a second thing said about it.
    """
    middle = top + _ROW / 2
    type_width = _text_width(column.data_type or "", _TYPE_SIZE)
    name_x = x + _PAD_X + _ICONS
    room = _KEY_ROOM if column.is_primary_key else 0.0
    name_limit = width - 2 * _PAD_X - _ICONS - room
    if column.data_type:
        name_limit -= type_width + _TYPE_GAP

    shown = _fit(column.name, name_limit, _COLUMN_SIZE)
    parts = ["<g>"]

    if column.is_joined:
        parts.append(_link_mark(x + _PAD_X + _ICONS / 2, middle))

    parts.append(
        _text(
            shown,
            x=name_x,
            y=middle + 4,
            size=_COLUMN_SIZE,
            fill="var(--ea-ink)",
        )
    )

    if column.is_primary_key:
        parts.append(
            _key_mark(name_x + _text_width(shown, _COLUMN_SIZE) + _KEY_GAP, middle)
        )

    if column.data_type:
        parts.append(
            _text(
                column.data_type,
                x=x + width - _PAD_X,
                y=middle + 4,
                size=_TYPE_SIZE,
                fill="var(--ea-muted)",
                anchor="end",
            )
        )

    parts.append("</g>")
    return "".join(parts)


def _key_mark(x: float, y: float) -> str:
    """Return the mark of a column the table is read by."""
    return (
        '<g class="ea-key"><title>primary key</title>'
        f'<circle cx="{x:.1f}" cy="{y:.1f}" r="2.6" fill="none" '
        'stroke="var(--ea-accent)" stroke-width="1.1"/>'
        f'<path d="M {x + 2.6:.1f} {y:.1f} h 4.4 M {x + 5.6:.1f} {y:.1f} v 2.2" '
        'fill="none" stroke="var(--ea-accent)" stroke-width="1.1" '
        'stroke-linecap="round"/></g>'
    )


def _link_mark(x: float, y: float) -> str:
    """Return the mark of a column a drawn relationship joins.

    Two links of a chain, turned across the row: the same mark the canvas
    draws, so that a picture and its still copy say a thing the same way.
    """
    top = y - 1.7

    def ring(left: float) -> str:
        return (
            f'<rect x="{left:.1f}" y="{top:.1f}" width="6" height="3.4" '
            'rx="1.7" fill="none" stroke="var(--ea-accent)" '
            'stroke-width="1.1"/>'
        )

    return (
        '<g class="ea-link"><title>joined by a relationship</title>'
        f'<g transform="rotate(-45 {x:.1f} {y:.1f})">'
        f"{ring(x - 5)}{ring(x - 1)}"
        "</g></g>"
    )


def _edge_markup(
    edge: DiagramEdge,
    boxes: dict[str, _Rect],
    direction: LayoutDirection,
    uid: str,
) -> str:
    """Return one line of the picture, with the cardinality it is read with."""
    source = boxes.get(edge.source_entity_id)
    target = boxes.get(edge.target_entity_id)

    if source is None or target is None:
        return ""

    start, control_1, control_2, end = _curve(
        source,
        target,
        direction,
        _ARROW_REACH if edge.direction is FilterDirection.BOTH else 0.0,
    )
    middle = (
        (start[0] + 3 * control_1[0] + 3 * control_2[0] + end[0]) / 8,
        (start[1] + 3 * control_1[1] + 3 * control_2[1] + end[1]) / 8,
    )
    path = (
        f"M {start[0]:.1f} {start[1]:.1f} "
        f"C {control_1[0]:.1f} {control_1[1]:.1f} "
        f"{control_2[0]:.1f} {control_2[1]:.1f} "
        f"{end[0]:.1f} {end[1]:.1f}"
    )
    marker_start = (
        f' marker-start="url(#{uid}-arrow)"'
        if edge.direction is FilterDirection.BOTH
        else ""
    )

    return (
        "<g>"
        f"<title>{escape(edge.name)}</title>"
        f'<path d="{path}" fill="none" stroke="var(--ea-edge)" '
        f'stroke-width="1.5" marker-end="url(#{uid}-arrow)"{marker_start}/>'
        f"{_cardinality_mark(MARKS[edge.cardinality], *middle)}"
        "</g>"
    )


def _curve(
    source: _Rect,
    target: _Rect,
    direction: LayoutDirection,
    begin_gap: float = 0.0,
) -> tuple[
    tuple[float, float],
    tuple[float, float],
    tuple[float, float],
    tuple[float, float],
]:
    """Return where a line leaves one box and reaches the next.

    A line leaves the side the layout reads through — the bottom of a box when
    the picture is stacked downwards, its right when it is stacked across — and
    reaches the opposite side of the box it joins. ``begin_gap`` moves the near
    end along that side, which is what leaves room for an arrowhead there.
    """
    if direction == "horizontal":
        start = (
            source.x + source.width + begin_gap,
            source.y + source.height / 2,
        )
        end = (target.x, target.y + target.height / 2)
        bend = _bend(abs(end[0] - start[0]))

        return (
            start,
            (start[0] + bend, start[1]),
            (end[0] - bend, end[1]),
            end,
        )

    start = (
        source.x + source.width / 2,
        source.y + source.height + begin_gap,
    )
    end = (target.x + target.width / 2, target.y)
    bend = _bend(abs(end[1] - start[1]))

    return (
        start,
        (start[0], start[1] + bend),
        (end[0], end[1] - bend),
        end,
    )


def _bend(distance: float) -> float:
    """Return how far a line is carried along the axis it is drawn on.

    A short join bends little and a long one bends more, but never so much that
    the curve doubles back: a line that overshot would read as a loop between
    two boxes that stand beside each other, where what is drawn is one join.
    """
    if distance <= 0.0:
        return _MIN_BEND

    return min(max(_MIN_BEND, distance * 0.45), distance / 2)


def _cardinality_mark(mark: str, x: float, y: float) -> str:
    """Return the chip a cardinality is written on, at the middle of a line."""
    width = _text_width(mark, 10.0) + 10.0

    return (
        '<g class="ea-cardinality">'
        f'<rect x="{x - width / 2:.1f}" y="{y - 8:.1f}" width="{width:.1f}" '
        'height="16" rx="8" fill="var(--ea-edge)"/>'
        f'<text x="{x:.1f}" y="{y + 3.5:.1f}" text-anchor="middle" '
        'font-size="10" font-weight="600" fill="var(--ea-on-accent)">'
        f"{escape(mark)}</text></g>"
    )


def _arrowhead(uid: str) -> str:
    """Return the arrowhead both ends of a two-way line are drawn with."""
    return (
        f'<marker id="{uid}-arrow" viewBox="0 0 10 10" refX="9" refY="5" '
        'markerWidth="7" markerHeight="7" orient="auto-start-reverse">'
        '<path d="M 0 0 L 10 5 L 0 10 z" fill="var(--ea-edge)"/></marker>'
    )


def _text(
    value: str,
    *,
    x: float,
    y: float,
    size: float,
    fill: str,
    limit: float | None = None,
    weight: str | None = None,
    anchor: str | None = None,
) -> str:
    """Return a piece of text, shortened when it would not fit its box."""
    shown = value if limit is None else _fit(value, limit, size)
    weight_attribute = "" if weight is None else f' font-weight="{weight}"'
    anchor_attribute = "" if anchor is None else f' text-anchor="{anchor}"'

    return (
        f'<text x="{x:.1f}" y="{y:.1f}" font-size="{size}"'
        f"{weight_attribute}{anchor_attribute} "
        f'fill="{fill}">{escape(shown)}</text>'
    )


def _fit(value: str, limit: float, size: float) -> str:
    """Return ``value`` shortened with an ellipsis when it is wider than ``limit``."""
    if limit <= 0:
        return ""

    fits = int(limit / (size * _CHAR))
    if len(value) <= fits:
        return value
    if fits <= 1:
        return "…"

    return value[: fits - 1] + "…"


def _text_width(value: str, size: float) -> float:
    """Return about how wide ``value`` is drawn at ``size``."""
    return len(value) * size * _CHAR


def _style(uid: str, theme: Theme) -> str:
    """Return the stylesheet of one diagram, scoped to it by its identity.

    A theme that names a palette names it and nothing else: a picture asked for
    light is light on a dark screen too, because asking for it is the answer.
    ``"auto"`` names both and lets the screen decide between them.
    """
    light = variables(PALETTE)
    dark = variables(DARK_PALETTE)
    frame = (
        f"#{uid}"
        "{background:var(--ea-surface);border:1px solid var(--ea-line);"
        "border-radius:8px;padding:12px 14px;overflow:auto;"
        "font-family:ui-sans-serif,-apple-system,BlinkMacSystemFont,"
        '"Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif;'
        "line-height:1.2;}"
        f"#{uid} svg{{display:block;max-width:100%;height:auto;}}"
        f"#{uid} .ea-title{{color:var(--ea-ink);font-size:13px;"
        "font-weight:600;margin:0 0 8px;}"
        f"#{uid} .ea-empty{{color:var(--ea-muted);font-size:12px;margin:0;}}"
    )

    if theme == "dark":
        return f"#{uid}{{{dark}{frame}"
    if theme == "light":
        return f"#{uid}{{{light}{frame}"

    return (
        f"#{uid}{{{light}{frame}"
        "@media (prefers-color-scheme:dark){"
        f"#{uid}{{{dark}}}"
        "}"
        f'body[data-jp-theme-light="false"] #{uid}{{{dark}}}'
        f".vscode-dark #{uid},.vscode-high-contrast #{uid}{{{dark}}}"
    )
