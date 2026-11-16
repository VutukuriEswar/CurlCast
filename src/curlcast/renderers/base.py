"""Renderer strategy contract and terminal fitting rules.

A renderer turns one RGB frame into a terminal-ready string. It owns two
things:

1. **Geometry** - how many sampled pixels map onto one character cell.
2. **Encoding** - how those pixels become glyphs and ANSI colour.

Aspect correction
-----------------
Terminal cells are roughly twice as tall as they are wide. ``PIXEL_ASPECT``
is the number of sampled pixel *rows* per character row:

* ``2.0`` - HD blocks: one cell draws a 1x2 pixel pair (square pixels).
* ``1.0`` - ASCII: one glyph per pixel; the 2:1 cell already restores the
  aspect ratio, so the sample height equals the row budget.

Getting this backwards is the classic cause of stretched terminal art (and
of ASCII output that is twice as tall as the requested row budget).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import Enum

import numpy as np
from PIL import Image

from curlcast.terminal import get_size


class RenderMode(str, Enum):
    """Supported renderer names (also the Typer option values)."""

    HD = "hd"
    ASCII = "ascii"


class BaseRenderer(ABC):
    """Abstract strategy for terminal renderers.

    Subclasses implement :meth:`render`. To add a new visual style (Braille,
    edge detection, ...) subclass this class, set ``PIXEL_ASPECT`` and
    register it with :func:`curlcast.renderers.register_renderer`.
    """

    #: Sampled pixel rows per character row. 2 = half blocks, 1 = ASCII.
    PIXEL_ASPECT: float = 2.0

    def __init__(self, width: int = 0, color: bool = True, rows: int = 0) -> None:
        size = get_size()
        # Never paint the last column: terminals set a "wrap pending" flag on
        # the final cell, which turns the next newline into a blank line.
        self.cols: int = width if width > 0 else max(size.columns - 1, 10)
        # Leave the bottom row free so the shell prompt has somewhere to land.
        self.rows: int = rows if rows > 0 else max(size.rows - 1, 4)
        self.color: bool = color

    # ------------------------------------------------------------------
    # Geometry
    # ------------------------------------------------------------------

    @property
    def target_cols(self) -> int:
        """Backwards-compatible alias for :attr:`cols`."""
        return self.cols

    @property
    def target_rows(self) -> int:
        """Backwards-compatible alias for :attr:`rows`."""
        return self.rows

    def fit(self, src_w: int, src_h: int, *, upscale: bool = False) -> tuple[int, int]:
        """Return the pixel grid to sample for a ``src_w`` x ``src_h`` source.

        The grid always fits ``cols`` x ``rows`` * ``PIXEL_ASPECT`` and keeps
        the source aspect ratio (in sampled pixels). Small sources are left
        alone unless ``upscale`` is true (useful for ``curlcast view``).
        """
        max_w = max(1, self.cols)
        max_h = max(1, int(self.rows * self.PIXEL_ASPECT))
        if src_w <= 0 or src_h <= 0:
            return max_w, max_h

        scale = min(max_w / src_w, max_h / src_h)
        if not upscale:
            scale = min(scale, 1.0)

        width = max(1, min(max_w, int(round(src_w * scale))))
        height = max(1, min(max_h, int(round(src_h * scale))))
        return width, height

    def pixel_dimensions(self) -> tuple[int, int]:
        """Native pixel grid for generated content (the demo)."""
        height = max(1, int(round(self.rows * self.PIXEL_ASPECT)))
        return self.cols, height

    def resize_image(self, image: Image.Image, *, upscale: bool = False) -> Image.Image:
        """Resize a PIL image to :meth:`fit`-computed dimensions."""
        rgb = image.convert("RGB")
        width, height = self.fit(*rgb.size, upscale=upscale)
        if rgb.size == (width, height):
            return rgb
        return rgb.resize((width, height), Image.Resampling.LANCZOS)

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    @abstractmethod
    def render(self, frame: np.ndarray) -> str:
        """Encode an ``(H, W, 3)`` uint8 RGB array as terminal text."""

    def render_frame(self, image: Image.Image) -> str:
        """Encode an already-sized PIL image (plugin convenience API)."""
        rgb = image if image.mode == "RGB" else image.convert("RGB")
        return self.render(np.asarray(rgb, dtype=np.uint8))

    def render_image(self, image: Image.Image, *, upscale: bool = False) -> str:
        """Resize a PIL image to fit the terminal, then render it."""
        return self.render_frame(self.resize_image(image, upscale=upscale))

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"{type(self).__name__}(cols={self.cols}, rows={self.rows}, "
            f"color={self.color})"
        )
