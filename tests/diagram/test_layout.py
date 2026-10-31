"""Tests for the layered layout of a semantic diagram."""

from __future__ import annotations

from typing import cast

import pytest
from etlalchemy.diagram.layout import (
    Join,
    LayoutDirection,
    Spot,
    Standing,
    layout_of,
)


def box(
    entity_id: str,
    width: float = 240.0,
    height: float = 120.0,
) -> Standing:
    return Standing(entity_id, width, height)


def spot_of(spots: tuple[Spot, ...], entity_id: str) -> Spot:
    return next(spot for spot in spots if spot.entity_id == entity_id)


def test_layout_of_no_boxes_is_empty() -> None:
    assert layout_of([], []) == ()


def test_layout_stacks_layers_rightwards_by_default() -> None:
    spots = layout_of([box("a"), box("b")], [Join("a", "b")])

    assert spot_of(spots, "a").x < spot_of(spots, "b").x
    assert spot_of(spots, "a").y == spot_of(spots, "b").y


def test_layout_puts_a_joined_box_after_the_box_it_is_joined_from() -> None:
    spots = layout_of([box("a"), box("b")], [Join("a", "b")], "vertical")

    assert spot_of(spots, "a").y < spot_of(spots, "b").y
    assert spot_of(spots, "a").x == spot_of(spots, "b").x


def test_layout_puts_unjoined_boxes_side_by_side() -> None:
    spots = layout_of([box("a"), box("b")], [], "vertical")

    assert spot_of(spots, "a").y == 0
    assert spot_of(spots, "b").y == 0
    assert spot_of(spots, "b").x == spot_of(spots, "a").x + 240.0 + 112.0


def test_layout_stacks_unjoined_boxes_one_under_another_across() -> None:
    spots = layout_of([box("a"), box("b")], [], "horizontal")

    assert spot_of(spots, "a").x == 0
    assert spot_of(spots, "b").x == 0
    assert spot_of(spots, "b").y == spot_of(spots, "a").y + 120.0 + 72.0


def test_layout_stacks_a_box_after_everything_that_joins_into_it() -> None:
    joins = [Join("a", "b"), Join("a", "c"), Join("b", "c")]

    spots = layout_of([box("a"), box("b"), box("c")], joins, "vertical")

    assert spot_of(spots, "a").y < spot_of(spots, "b").y
    assert spot_of(spots, "b").y < spot_of(spots, "c").y


def test_layout_gives_a_circle_a_place_without_following_it() -> None:
    joins = [Join("a", "b"), Join("b", "a")]

    spots = layout_of([box("a"), box("b")], joins, "vertical")

    assert spot_of(spots, "a").y < spot_of(spots, "b").y


def test_layout_runs_down_when_asked_to() -> None:
    spots = layout_of([box("a"), box("b")], [Join("a", "b")], "vertical")

    assert spot_of(spots, "a").y < spot_of(spots, "b").y
    assert spot_of(spots, "a").x == spot_of(spots, "b").x


def test_layout_anchors_the_picture_at_the_origin() -> None:
    spots = layout_of([box("a"), box("b")], [Join("a", "b")])

    assert min(spot.x for spot in spots) == 0
    assert min(spot.y for spot in spots) == 0


def test_layout_keeps_the_order_it_was_given_within_a_row() -> None:
    spots = layout_of([box("b"), box("a", height=60.0)], [], "vertical")

    assert spot_of(spots, "b").x < spot_of(spots, "a").x


def test_layout_keeps_a_join_from_spanning_a_row_it_does_not_need() -> None:
    """A box joined into a deep row stands beside that row, not two rows up.

    Otherwise its line is drawn across the row in between, and the boxes in
    that row are drawn on top of it.
    """
    boxes = [box("a"), box("b"), box("c"), box("product")]
    joins = [Join("a", "b"), Join("b", "c"), Join("product", "c")]

    spots = layout_of(boxes, joins, "vertical")

    assert spot_of(spots, "product").y == spot_of(spots, "b").y


def test_layout_orders_a_row_so_its_joins_do_not_cross() -> None:
    boxes = [box("a"), box("b"), box("c"), box("d")]
    joins = [Join("a", "d"), Join("b", "c")]

    spots = layout_of(boxes, joins, "vertical")

    assert spot_of(spots, "d").x < spot_of(spots, "c").x


def test_layout_centres_a_row_under_the_one_above_it() -> None:
    boxes = [box("a"), box("b"), box("d")]
    joins = [Join("a", "d"), Join("b", "d")]

    spots = layout_of(boxes, joins, "vertical")

    assert spot_of(spots, "d").x == 176.0


def test_layout_rejects_a_direction_it_does_not_know() -> None:
    with pytest.raises(ValueError, match="Unknown layout direction"):
        layout_of([box("a")], [], cast(LayoutDirection, "diagonal"))
