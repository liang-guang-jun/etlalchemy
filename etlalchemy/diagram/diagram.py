"""What a diagram of a semantic model holds.

A diagram is a selection of a model's entities and the relationships between
them, drawn as boxes and lines: what is drawn is fixed when the diagram is
made, and where the boxes stand is worked out when it is rendered, because the
same diagram may be laid out down the page or across it.

These are value objects only. Building one from a model is
:class:`~etlalchemy.diagram.service.DiagramService`, and drawing one is
:mod:`etlalchemy.diagram.render`.
"""

from __future__ import annotations

from dataclasses import dataclass
from html import escape
from typing import TYPE_CHECKING, Any, cast

from etlalchemy.semantic.relationship import Cardinality, FilterDirection

if TYPE_CHECKING:
    from etlalchemy.diagram.layout import LayoutDirection
    from etlalchemy.diagram.theme import Theme


@dataclass(frozen=True, slots=True)
class DiagramColumn:
    """One column of a box, as it is drawn.

    Attributes:
        name: Column name, as the rowset spells it.
        data_type: SQL spelling of the column's type, or ``None`` when it has
            none declared.
        is_primary_key: Whether the column belongs to the primary key, which
            is drawn as the key that reads the table.
        is_joined: Whether a relationship drawn on the diagram joins it.
    """

    name: str
    data_type: str | None = None
    is_primary_key: bool = False
    is_joined: bool = False


@dataclass(frozen=True, slots=True)
class DiagramNode:
    """One box of a diagram: an entity, and what it is made of.

    Attributes:
        entity_id: Identifier of the entity drawn.
        name: Name the model gives the entity.
        columns: Columns of the entity, in declaration order.
        table: Qualified name of the table the entity stands for, or ``None``
            when the entity is not backed by a physical table.
    """

    entity_id: str
    name: str
    columns: tuple[DiagramColumn, ...] = ()
    table: str | None = None


@dataclass(frozen=True, slots=True)
class DiagramEdge:
    """One line of a diagram: a relationship, and how it is read.

    Attributes:
        relationship_id: Identifier of the relationship drawn.
        name: Name the model gives the relationship.
        source_entity_id: Entity the relationship is read from.
        target_entity_id: Entity the relationship is read to.
        source_columns: Columns joined on the source side, in join order.
        target_columns: Columns joined on the target side, in join order.
        cardinality: How many rows match on either side.
        direction: Whether the relationship is read one way or both.
        priority: Preference between this relationship and others joining
            the same two entities.
    """

    relationship_id: str
    name: str
    source_entity_id: str
    target_entity_id: str
    source_columns: tuple[str, ...] = ()
    target_columns: tuple[str, ...] = ()
    cardinality: Cardinality = Cardinality.ONE_TO_MANY
    direction: FilterDirection = FilterDirection.SINGLE
    priority: int = 1


@dataclass(frozen=True, slots=True)
class Diagram:
    """A picture of some of a model's entities and the joins between them.

    Attributes:
        nodes: Entities drawn, in the order they are read in.
        edges: Relationships drawn, in model declaration order. A
            relationship is drawn only when both of its ends are.
    """

    nodes: tuple[DiagramNode, ...] = ()
    edges: tuple[DiagramEdge, ...] = ()

    def __post_init__(self) -> None:
        """Freeze the node and edge collections into tuples."""
        object.__setattr__(self, "nodes", tuple(self.nodes))
        object.__setattr__(self, "edges", tuple(self.edges))

    def __len__(self) -> int:
        """Return how many entities the diagram draws."""
        return len(self.nodes)

    def node_for(self, entity_id: str) -> DiagramNode:
        """Return the box drawn for ``entity_id``.

        Args:
            entity_id: Identifier of the entity drawn.

        Returns:
            The matching box.

        Raises:
            KeyError: If the diagram draws no entity with that id.
        """
        for node in self.nodes:
            if node.entity_id == entity_id:
                return node
        raise KeyError(f"Diagram draws no entity: {entity_id!r}")

    def to_html(
        self,
        *,
        direction: LayoutDirection = "vertical",
        title: str | None = None,
        show_columns: bool = True,
        theme: Theme = "light",
    ) -> str:
        """Return the diagram as a self-contained HTML fragment.

        Args:
            direction: ``"vertical"`` to stack relationship depth downwards,
                ``"horizontal"`` to stack it rightwards.
            title: Heading drawn above the picture, or ``None`` for none.
            show_columns: Whether to draw the columns of each entity, or only
                the boxes and the joins between them.
            theme: ``"light"`` or ``"dark"`` to draw in that palette, or
                ``"auto"`` to follow the screen the picture is read on.

        Returns:
            An HTML fragment holding the styled SVG picture.

        Raises:
            ValueError: If ``theme`` names no palette.
        """
        from etlalchemy.diagram.render import render_html

        return render_html(
            self,
            direction=direction,
            title=title,
            show_columns=show_columns,
            theme=theme,
        )

    def render(
        self,
        *,
        direction: LayoutDirection = "horizontal",
        title: str | None = None,
        show_columns: bool = True,
        interactive: bool = True,
        theme: Theme = "light",
    ) -> object:
        """Draw the diagram in a notebook.

        In a notebook the returned value draws itself when it is the value of a
        cell, like any other display object:

            model.diagram("Customer", "Order").render()

        By default the picture is a canvas a reader can drag, zoom, point at
        and lay out again. ``interactive=False`` draws the same picture as a
        still SVG, which needs nothing fetched and nothing scripted.

        Outside a notebook, where :mod:`IPython` is not installed, the document
        is returned as a plain string, which is what an application embedding
        the diagram would serve.

        Args:
            direction: ``"vertical"`` to stack relationship depth downwards,
                ``"horizontal"`` to stack it rightwards.
            title: Heading drawn above the picture, or ``None`` for none.
            show_columns: Whether to draw the columns of each entity.
            interactive: Whether to draw the canvas rather than the still
                picture.
            theme: ``"light"`` or ``"dark"`` to draw in that palette, or
                ``"auto"`` to follow the screen the picture is read on.

        Returns:
            An :class:`IPython.display.HTML` display object when IPython is
            available, otherwise the HTML as a :class:`str`.

        Raises:
            ValueError: If ``theme`` names no palette.
        """
        if not interactive:
            still = self.to_html(
                direction=direction,
                title=title,
                show_columns=show_columns,
                theme=theme,
            )
            display = _html_display(still)

            return still if display is None else display

        from etlalchemy.diagram.interactive import (
            interactive_html,
            picture_height,
        )

        document = interactive_html(
            self,
            direction=direction,
            title=title,
            show_columns=show_columns,
            theme=theme,
        )
        frame = _frame(
            document,
            height=picture_height(
                self,
                direction=direction,
                show_columns=show_columns,
                title=title,
            ),
            title="Semantic model diagram" if title is None else title,
        )
        display = _html_display(frame)

        return document if display is None else display

    def to_interactive_html(
        self,
        *,
        direction: LayoutDirection = "vertical",
        title: str | None = None,
        show_columns: bool = True,
        theme: Theme = "light",
    ) -> str:
        """Return the diagram as a self-contained interactive document.

        The document holds the canvas, the data it draws, and the still picture
        it falls back to, and it fetches React and React Flow from a CDN. It is
        what a served page or a saved file holds.

        Args:
            direction: ``"vertical"`` to stack relationship depth downwards,
                ``"horizontal"`` to stack it rightwards.
            title: Heading drawn above the picture, or ``None`` for none.
            show_columns: Whether to draw the columns of each entity.
            theme: ``"light"`` or ``"dark"`` to draw in that palette, or
                ``"auto"`` to follow the screen the picture is read on.

        Returns:
            One HTML document.

        Raises:
            ValueError: If ``theme`` names no palette.
        """
        from etlalchemy.diagram.interactive import interactive_html

        return interactive_html(
            self,
            direction=direction,
            title=title,
            show_columns=show_columns,
            theme=theme,
        )

    def _repr_html_(self) -> str:
        """Draw the canvas when the diagram is a notebook cell's value.

        The canvas is the picture a reader can ask questions of, and it carries
        the still picture it falls back to, so a cell holding a diagram draws
        the same thing :meth:`render` does. :meth:`to_html` is the way to ask
        for the still picture alone.
        """
        from etlalchemy.diagram.interactive import (
            interactive_html,
            picture_height,
        )

        return _frame(
            interactive_html(self),
            height=picture_height(self),
            title="Semantic model diagram",
        )


def _frame(document: str, *, height: int, title: str) -> str:
    """Return a document framed in the page, at the height it needs."""
    return (
        '<div class="etlalchemy-diagram-frame" style="width:100%">'
        f'<iframe title="{escape(title)}" scrolling="no" '
        'style="width:100%;border:0;overflow:hidden;'
        f'height:{height}px" srcdoc="{escape(document, quote=True)}"></iframe>'
        "</div>"
    )


def _html_display(html: str) -> object | None:
    """Return a notebook display object for ``html``, or ``None`` without IPython."""
    try:
        import IPython.display
    except ImportError:
        return None

    # IPython's own signatures are untyped, so the boundary is made explicit here.
    display_type: Any = IPython.display.HTML

    return cast(object, display_type(html))
