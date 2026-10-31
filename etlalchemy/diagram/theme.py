"""The two palettes a diagram is drawn in.

A diagram is read in a notebook that may be light or dark, so its colours are
custom properties set in one place and read by whichever picture is drawn: the
static SVG names them in its own stylesheet, and the interactive canvas hands
the same names to React Flow's own variables. Nothing here is a colour of its
own, so a theme change moves the picture with the rest of the screen.

A picture is drawn light unless it is asked for otherwise: what a diagram is
read on is a choice, and the choice a reader makes of it is the one that
should be drawn. ``"auto"`` is there for a caller who would rather the picture
follow the screen it is read on.
"""

from __future__ import annotations

from typing import Literal, cast

# How a picture is coloured: one palette, or the reader's own.
type Theme = Literal["light", "dark", "auto"]

_THEMES: tuple[str, ...] = ("light", "dark", "auto")

LIGHT: Theme = "light"
DARK: Theme = "dark"
AUTO: Theme = "auto"


def checked(theme: str) -> Theme:
    """Return ``theme`` once it is known to name a palette.

    Args:
        theme: The theme a caller asked for.

    Returns:
        The same theme, narrowed to the ones this package draws.

    Raises:
        ValueError: If ``theme`` names no palette.
    """
    if theme not in _THEMES:
        raise ValueError(
            f"Unknown theme: {theme!r}; expected one of {', '.join(_THEMES)}"
        )

    return cast(Theme, theme)


PALETTE: dict[str, str] = {
    "--ea-surface": "#ffffff",
    "--ea-surface-raised": "#fbfbfa",
    "--ea-surface-hover": "#f3f4f6",
    "--ea-ink": "#1f2328",
    "--ea-muted": "#656d76",
    "--ea-line": "#d0d7de",
    "--ea-edge": "#8c959f",
    "--ea-accent": "#0969da",
    "--ea-accent-soft": "#ddf4ff",
    "--ea-on-accent": "#ffffff",
}

DARK_PALETTE: dict[str, str] = {
    "--ea-surface": "#0d1117",
    "--ea-surface-raised": "#161b22",
    "--ea-surface-hover": "#21262d",
    "--ea-ink": "#e6edf3",
    "--ea-muted": "#8b949e",
    "--ea-line": "#30363d",
    "--ea-edge": "#6e7681",
    "--ea-accent": "#4493f8",
    "--ea-accent-soft": "#12283f",
    "--ea-on-accent": "#0d1117",
}


def variables(palette: dict[str, str]) -> str:
    """Return the custom properties of one palette as stylesheet text."""
    return "".join(f"{name}:{value};" for name, value in palette.items())
