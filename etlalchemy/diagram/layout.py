"""Where the boxes of a semantic diagram stand.

A picture of a model is read along its joins, so the layout is read that way
too: a box stands in the row (or column) of how many joins deep it is, and
every join points down (or right). That is what makes the picture say what the
model says — the thing joined from stands before the thing joined to — where a
grid of cards says only how many there are.

Two rules keep the joins visible rather than drawn under a box. A box is never
put deeper than its joins require, so a dimension table stands beside the row
it feeds instead of two rows above it, and a join is drawn between two rows
that are next to each other. Within a row the boxes are ordered by where the
boxes they are joined to stand, which is what keeps two joins from being drawn
across one another.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

# The axis along which relationship depth is drawn.
type LayoutDirection = Literal["vertical", "horizontal"]

_VERTICAL: LayoutDirection = "vertical"
_HORIZONTAL: LayoutDirection = "horizontal"

# How much room a box is left around itself: enough that two of them read as two.
_GAP_X = 112.0
# The room between two rows is where a join and its label are drawn, so it is
# wider than the room between two boxes would need to be.
_GAP_Y = 72.0
# How many times a row is re-ordered against its neighbours. Two sweeps settle
# most pictures; the rest only move a box one place, and the count keeps the
# result the same every time the picture is drawn.
_SWEEPS = 4


@dataclass(frozen=True, slots=True)
class Standing:
    """One box of a picture: what it is, and how big it is drawn.

    Attributes:
        id: Entity identifier the box stands for.
        width: Drawn width of the box.
        height: Drawn height of the box.
    """

    id: str
    width: float
    height: float


@dataclass(frozen=True, slots=True)
class Join:
    """One join of a picture, which is what says which box comes after which."""

    from_entity_id: str
    to_entity_id: str


@dataclass(frozen=True, slots=True)
class Spot:
    """Where one box is to stand, once the picture has been laid out."""

    entity_id: str
    x: float
    y: float


def layout_of(
    boxes: Sequence[Standing],
    joins: Sequence[Join],
    direction: LayoutDirection = _HORIZONTAL,
) -> tuple[Spot, ...]:
    """Return where every box of a picture should stand.

    A picture of a model is read along its joins, so the layout is read that
    way as well: a box stands in the row (or column) of how many joins deep it
    is, and every join points down (or right). Within a row the boxes are
    ordered by where the boxes they are joined to stand, and each row is
    centred under the widest one, so that a join is drawn beside the boxes
    rather than across them. The whole arrangement is anchored at the origin,
    so that laying a picture out twice leaves it in the same place.

    A picture whose joins run in a circle has no such order, so a join that
    would step back into what is already being walked is left out of the depth
    rather than followed: the boxes still get layers, and the one the circle
    closes on stands beside the one it came from.

    Args:
        boxes: The boxes to place, in the order they are to be read in.
        joins: The joins between them, as drawn.
        direction: ``"vertical"`` to stack layers downwards, ``"horizontal"``
            to stack them rightwards.

    Returns:
        One spot per box, anchored at the origin.

    Raises:
        ValueError: If ``direction`` is neither ``"vertical"`` nor
            ``"horizontal"``.
    """
    if direction not in (_VERTICAL, _HORIZONTAL):
        raise ValueError(f"Unknown layout direction: {direction!r}")

    if not boxes:
        return ()

    vertical = direction == _VERTICAL
    depths = _pulled_down(_depths_of(boxes, joins), boxes, joins)
    layers = _ordered_layers(boxes, joins, depths)

    sizes = {
        depth: sum(box.width if vertical else box.height for box in layer)
        + _across_gap(vertical) * (len(layer) - 1)
        for depth, layer in layers.items()
    }
    widest = max(sizes.values())

    spots: list[Spot] = []
    primary = 0.0

    for depth in sorted(layers):
        across = (widest - sizes[depth]) / 2
        layer_size = 0.0

        for box in layers[depth]:
            spots.append(
                Spot(
                    box.id,
                    across if vertical else primary,
                    primary if vertical else across,
                )
            )
            across += (box.width if vertical else box.height) + _across_gap(vertical)
            layer_size = max(layer_size, box.height if vertical else box.width)

        primary += layer_size + _layer_gap(vertical)

    return tuple(spots)


def _across_gap(vertical: bool) -> float:
    """Return the room left between two boxes standing in the same layer."""
    return _GAP_X if vertical else _GAP_Y


def _layer_gap(vertical: bool) -> float:
    """Return the room left between two layers, which is where joins are drawn."""
    return _GAP_Y if vertical else _GAP_X


def _neighbours(
    boxes: Sequence[Standing],
    joins: Sequence[Join],
) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    """Return the boxes each box joins to, and the boxes it is joined from."""
    known = {box.id for box in boxes}
    onwards: dict[str, list[str]] = {}
    inwards: dict[str, list[str]] = {}

    for join in joins:
        if join.from_entity_id == join.to_entity_id:
            continue
        if join.from_entity_id not in known or join.to_entity_id not in known:
            continue
        onwards.setdefault(join.from_entity_id, []).append(join.to_entity_id)
        inwards.setdefault(join.to_entity_id, []).append(join.from_entity_id)

    return onwards, inwards


def _ordered_layers(
    boxes: Sequence[Standing],
    joins: Sequence[Join],
    depths: dict[str, int],
) -> dict[int, list[Standing]]:
    """Return the boxes of every layer, ordered so that its joins cross least.

    A layer is ordered by where its boxes' neighbours stand in the layer before
    it, then re-ordered by where they stand in the layer after it, and so on.
    A box moves towards the boxes it is joined to, which is what stops two
    joins from being drawn across each other.
    """
    layers: dict[int, list[Standing]] = {}

    for box in boxes:
        layers.setdefault(depths.get(box.id, 0), []).append(box)

    onwards, inwards = _neighbours(boxes, joins)
    ordered = sorted(layers)

    for _ in range(_SWEEPS):
        for depth in ordered[1:]:
            layer = layers[depth]
            layers[depth] = _reordered(layer, inwards, layers.get(depth - 1, []))
        for depth in reversed(ordered[:-1]):
            layer = layers[depth]
            layers[depth] = _reordered(layer, onwards, layers.get(depth + 1, []))

    # Pulling a box down can leave a layer with nothing in it; a row with no
    # boxes in it is not a row, so it is not laid out.
    return {depth: layer for depth, layer in layers.items() if layer}


def _reordered(
    layer: list[Standing],
    neighbours: dict[str, list[str]],
    anchor: list[Standing],
) -> list[Standing]:
    """Return ``layer`` ordered by where each box's neighbours stand in ``anchor``.

    A box with no neighbour in ``anchor`` keeps the place it had, so that a box
    nothing joins to stays where the model declared it.
    """
    if not layer or not anchor:
        return layer

    stands = {box.id: index for index, box in enumerate(anchor)}
    ranked: list[tuple[float, int, Standing]] = []

    for index, box in enumerate(layer):
        places = [
            stands[other] for other in neighbours.get(box.id, ()) if other in stands
        ]
        where = index if not places else sum(places) / len(places)
        ranked.append((where, index, box))

    ranked.sort(key=lambda item: (item[0], item[1]))
    return [box for _, _, box in ranked]


def _pulled_down(
    depths: dict[str, int],
    boxes: Sequence[Standing],
    joins: Sequence[Join],
) -> dict[str, int]:
    """Return depths with every box standing as deep as its joins allow.

    Taking the longest walk to a box leaves a dimension table that only joins
    into a deep layer standing at the top of the picture, with its join drawn
    across every row in between — and every box in those rows drawn on top of
    that join. Moving such a box down beside the row it joins into shortens the
    join without changing what the picture says.
    """
    onwards, inwards = _neighbours(boxes, joins)
    depths = {box.id: depths.get(box.id, 0) for box in boxes}

    moved = True

    while moved:
        moved = False

        for box in sorted(boxes, key=lambda item: -depths[item.id]):
            after = [depths[other] for other in onwards.get(box.id, ())]
            if not after:
                continue

            wanted = min(after) - 1
            if wanted <= depths[box.id]:
                continue

            before = [depths[other] for other in inwards.get(box.id, ())]
            if before and wanted <= max(before):
                continue

            depths[box.id] = wanted
            moved = True

    return depths


def _depths_of(
    boxes: Sequence[Standing],
    joins: Sequence[Join],
) -> dict[str, int]:
    """Return how many joins deep each box stands, in the row it is laid out in.

    The longest walk to a box rather than the shortest, because a box that two
    things join into belongs after both of them: a row that let it stand early
    would be a picture with a join in it that has to be read backwards.
    """
    onwards, _ = _neighbours(boxes, joins)
    depth: dict[str, int] = {}

    def walk(entity_id: str, at: int, walked: frozenset[str]) -> None:
        known = depth.get(entity_id)

        if known is not None and known >= at:
            return

        depth[entity_id] = at

        for next_id in onwards.get(entity_id, []):
            if next_id in walked:
                continue
            walk(next_id, at + 1, walked | {entity_id})

    for box in boxes:
        walk(box.id, 0, frozenset())

    return depth
