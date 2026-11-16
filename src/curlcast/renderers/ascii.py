"""``--mode ascii``: a 70-glyph density ramp with optional truecolor.

The ramp runs from darkest (space) to brightest (``$``). Character selection
uses luminance; colour, when enabled, is painted per glyph with the source
pixel's RGB.

Contrast
--------
A fixed linear mapping wastes most of the ramp on typical photos. Instead each
frame is clipped to its 2nd-98th luminance percentile. For video that range is
smoothed with an exponential moving average, because recomputing it from
scratch every frame makes brightness "pump" as the scene changes.

Aspect
------
ASCII uses ``PIXEL_ASPECT = 1.0``: one glyph per sampled pixel. The terminal
cell is ~2:1, which restores the source aspect. Requesting two pixel rows per
cell (the HD behaviour) would emit twice the requested number of lines and
stretch the image vertically.
"""

from __future__ import annotations

import numpy as np

from curlcast.renderers._pixels import as_rgb, luma, pack_rgb
from curlcast.renderers.base import BaseRenderer

# 70 characters, dark -> bright.
RAMP = " .'`^\",:;Il!i><~+_-?][}{1)(|\\/tfjrxnuvczXYUJCLQ0OZmwqpdbkhao*#MW&8%B@$"
RAMP_ARRAY = np.array(list(RAMP), dtype="<U1")
_RESET = "\x1b[0m"
_MAX_CACHE = 16_384


class AsciiRenderer(BaseRenderer):
    """Luminance-ramp renderer with adaptive contrast and optional colour."""

    PIXEL_ASPECT: float = 1.0

    def __init__(self, width: int = 0, color: bool = True, rows: int = 0) -> None:
        super().__init__(width=width, color=color, rows=rows)
        self._low: float | None = None
        self._high: float | None = None
        self._color_cache: dict[int, str] = {}

    # ------------------------------------------------------------------
    def reset_contrast(self) -> None:
        """Forget the smoothed luminance window (call between media files)."""
        self._low = None
        self._high = None

    def _contrast_window(self, luminance: np.ndarray) -> tuple[float, float]:
        low = float(np.percentile(luminance, 2.0))
        high = float(np.percentile(luminance, 98.0))
        if high - low < 1.0:
            low, high = float(luminance.min()), float(luminance.max())
        if high - low < 1.0:
            high = low + 1.0

        if self._low is None or self._high is None:
            # First frame: adopt the exact window so static images are crisp.
            self._low, self._high = low, high
        else:
            smoothing = 0.2
            self._low = self._low * (1.0 - smoothing) + low * smoothing
            self._high = self._high * (1.0 - smoothing) + high * smoothing
        return self._low, max(self._high, self._low + 1.0)

    def _escape(self, packed: int) -> str:
        code = self._color_cache.get(packed)
        if code is not None:
            return code
        red = (packed >> 16) & 0xFF
        green = (packed >> 8) & 0xFF
        blue = packed & 0xFF
        code = f"\x1b[38;2;{red};{green};{blue}m"
        if len(self._color_cache) >= _MAX_CACHE:
            self._color_cache.clear()
        self._color_cache[packed] = code
        return code

    # ------------------------------------------------------------------
    def render(self, frame: np.ndarray) -> str:
        rgb = as_rgb(frame)
        height, width = rgb.shape[:2]
        if height == 0 or width == 0:
            return ""

        luminance = luma(rgb)
        low, high = self._contrast_window(luminance)
        scaled = np.clip((luminance - low) / (high - low), 0.0, 1.0)
        indices = (scaled * (RAMP_ARRAY.size - 1)).astype(np.intp)
        glyphs = RAMP_ARRAY[indices]

        if not self.color:
            return "\n".join("".join(row) for row in glyphs.tolist())

        packed = pack_rgb(rgb)
        lines: list[str] = []
        for row in range(height):
            glyph_row = glyphs[row].tolist()
            color_row = packed[row].tolist()
            parts: list[str] = []
            previous = -1
            for column in range(width):
                value = color_row[column]
                if value != previous:
                    parts.append(self._escape(value))
                    previous = value
                parts.append(glyph_row[column])
            parts.append(_RESET)
            lines.append("".join(parts))
        return "\n".join(lines)
