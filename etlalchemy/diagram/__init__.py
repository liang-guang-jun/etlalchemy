"""Diagram of a semantic model.

This package defines what a diagram is — the entities it draws, the columns
they are made of, and the relationships between them — plus where its boxes
stand and how it is drawn in a notebook.
"""

from __future__ import annotations

from etlalchemy.diagram.diagram import (
    Diagram,
    DiagramColumn,
    DiagramEdge,
    DiagramNode,
)
from etlalchemy.diagram.layout import (
    Join,
    LayoutDirection,
    Spot,
    Standing,
    layout_of,
)
from etlalchemy.diagram.service import DiagramService
from etlalchemy.diagram.theme import Theme

__all__ = [
    "Diagram",
    "DiagramColumn",
    "DiagramEdge",
    "DiagramNode",
    "DiagramService",
    "Join",
    "LayoutDirection",
    "Spot",
    "Standing",
    "Theme",
    "layout_of",
]
