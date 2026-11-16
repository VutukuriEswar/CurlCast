"""``--mode hd`` (default): Unicode upper-half blocks with 24-bit colour.

Each character cell paints two vertical pixels:

* foreground colour -> top pixel (``ESC[38;2;R;G;Bm``)
* background colour -> bottom pixel (``ESC[48;2;R;G;Bm``)
* glyph ``▀``

That doubles the vertical resolution of the terminal, which is what makes
faces and text legible instead of "pixel soup".

Performance
-----------
Naively formatting two escape sequences per cell costs ~18 ms per 120-column
frame, which misses a 20 fps budget on larger terminals. Two cheap tricks fix
it:

* cache formatted escapes by packed 24-bit colour (video reuses colours a
  lot: sky, skin, walls);
* only emit an escape when that pixel's colour actually changes, so long
  horizontal runs cost one sequence plus N glyphs.

Monochrome mode uses the four half-block states (``' '``, ``▀``, ``▄``,
``█``) at full 2-pixel resolution instead of throwing the bottom pixel away.
"""

from __future__ import annotations

import numpy as np

from curlcast.renderers._pixels import as_rgb, luma, pack_rgb
from curlcast.renderers.base import BaseRenderer

_RESET = "\x1b[0m"
_UPPER_HALF = "▀"
_MAX_CACHE = 16_384


class BlockRenderer(BaseRenderer):
    """Two-pixels-per-cell renderer with optional 24-bit TrueColor."""

    PIXEL_ASPECT: float = 2.0

    def __init__(self, width: int = 0, color: bool = True, rows: int = 0) -> None:
        super().__init__(width=width, color=color, rows=rows)
        self._fg_cache: dict[int, str] = {}
        self._bg_cache: dict[int, str] = {}

    # ------------------------------------------------------------------
    def _escape(self, packed: int, *, background: bool) -> str:
        cache = self._bg_cache if background else self._fg_cache
        code = cache.get(packed)
        if code is not None:
            return code
        red = (packed >> 16) & 0xFF
        green = (packed >> 8) & 0xFF
        blue = packed & 0xFF
        layer = "48" if background else "38"
        code = f"\x1b[{layer};2;{red};{green};{blue}m"
        if len(cache) >= _MAX_CACHE:
            cache.clear()
        cache[packed] = code
        return code

    # ------------------------------------------------------------------
    def render(self, frame: np.ndarray) -> str:
        rgb = as_rgb(frame)
        height, width = rgb.shape[:2]
        if height == 0 or width == 0:
            return ""

        if height % 2:
            rgb = np.vstack((rgb, np.zeros((1, width, 3), dtype=np.uint8)))
            height += 1

        packed = pack_rgb(rgb)
        top_rows = packed[0::2]
        bottom_rows = packed[1::2]
        line_count = height // 2

        if not self.color:
            return self._render_monochrome(rgb, top_rows, bottom_rows, line_count, width)
        return self._render_color(top_rows, bottom_rows, line_count, width)

    # ------------------------------------------------------------------
    def _render_color(
        self,
        top_rows: np.ndarray,
        bottom_rows: np.ndarray,
        line_count: int,
        width: int,
    ) -> str:
        lines: list[str] = []
        for row in range(line_count):
            top = top_rows[row].tolist()
            bottom = bottom_rows[row].tolist()
            parts: list[str] = []
            previous_top = previous_bottom = -1
            for column in range(width):
                top_value = top[column]
                if top_value != previous_top:
                    parts.append(self._escape(top_value, background=False))
                    previous_top = top_value
                bottom_value = bottom[column]
                if bottom_value != previous_bottom:
                    parts.append(self._escape(bottom_value, background=True))
                    previous_bottom = bottom_value
                parts.append(_UPPER_HALF)
            parts.append(_RESET)
            lines.append("".join(parts))
        return "\n".join(lines)

    # ------------------------------------------------------------------
    def _render_monochrome(
        self,
        rgb: np.ndarray,
        top_rows: np.ndarray,
        bottom_rows: np.ndarray,
        line_count: int,
        width: int,
    ) -> str:
        luminance = luma(rgb)
        # Adaptive midpoint: keeps dark footage readable instead of blank.
        threshold = max(24.0, float(np.percentile(luminance, 55.0)))

        top_light = luminance[0::2] >= threshold
        bottom_light = luminance[1::2] >= threshold
        if top_light.shape[0] < line_count:  # pragma: no cover - padding guard
            pad = np.zeros((line_count - top_light.shape[0], width), dtype=bool)
            top_light = np.vstack((top_light, pad))
            bottom_light = np.vstack((bottom_light, pad))

        glyphs = np.where(
            top_light,
            np.where(bottom_light, "█", "▀"),
            np.where(bottom_light, "▄", " "),
        )
        return "\n".join("".join(row) for row in glyphs.tolist())
