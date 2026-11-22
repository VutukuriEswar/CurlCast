from __future__ import annotations

import numpy as np
from PIL import Image, ImageFilter, ImageOps

from curlcast.renderers._pixels import as_rgb, luma, pack_rgb
from curlcast.renderers.base import BaseRenderer

RAMP = " `.-':_,^=;><+!rc*/z?sLTv)J7(|Fi{C}fI31tlu[neoZ5Yxjya]2ESwqkP6h9d4VpOGbUAKXHm8RD#$Bg0MNWQ%&@"

RAMP_BW = " .:-=+*#%@"

RAMP_ARRAY    = np.array(list(RAMP),    dtype="<U1")
RAMP_BW_ARRAY = np.array(list(RAMP_BW), dtype="<U1")

_RESET     = "\x1b[0m"
_MAX_CACHE = 16_384


class AsciiRenderer(BaseRenderer):
    PIXEL_ASPECT: float = 2.0

    def __init__(self, width: int = 0, color: bool = False, rows: int = 0) -> None:
        super().__init__(width=width, color=color, rows=rows)
        self._low:  float | None = None
        self._high: float | None = None
        self._color_cache: dict[int, str] = {}

    def fit(self, src_w: int, src_h: int, *, upscale: bool = False) -> tuple[int, int]:
        max_w = max(1, self.cols)
        max_h = max(1, self.rows)
        if src_w <= 0 or src_h <= 0:
            return max_w, max_h
        aspect = self.cell_aspect()
        scale = min(max_w / src_w, (max_h * aspect) / src_h)
        if not upscale:
            scale = min(scale, 1.0)
        width = max(1, min(max_w, int(round(src_w * scale))))
        height = max(1, min(max_h, int(round(src_h * scale / aspect))))
        return width, height

    def pixel_dimensions(self) -> tuple[int, int]:
        return self.cols, self.rows

    def resize_image(self, image: Image.Image, *, upscale: bool = False) -> Image.Image:
        rgb = image.convert("RGB")
        src_w, src_h = rgb.size

        pixel_w, pixel_h = self.fit(src_w, src_h, upscale=upscale)

        if rgb.size != (pixel_w, pixel_h):
            rgb = rgb.resize((pixel_w, pixel_h), Image.Resampling.LANCZOS)

        if not self.color:
            gray = ImageOps.grayscale(rgb)
            gray = ImageOps.equalize(gray)
            gray = gray.filter(
                ImageFilter.UnsharpMask(radius=1.5, percent=100, threshold=1)
            )
            rgb = gray.convert("RGB")

        return rgb

    def reset_contrast(self) -> None:
        self._low = None
        self._high = None

    def _contrast_window(self, luminance: np.ndarray) -> tuple[float, float]:
        low  = float(np.percentile(luminance, 1.0))
        high = float(np.percentile(luminance, 99.0))
        if high - low < 1.0:
            low, high = float(luminance.min()), float(luminance.max())
        if high - low < 1.0:
            high = low + 1.0

        if self._low is None or self._high is None:
            self._low, self._high = low, high
        else:
            alpha = 0.15
            self._low  = self._low  * (1.0 - alpha) + low  * alpha
            self._high = self._high * (1.0 - alpha) + high * alpha

        return self._low, max(self._high, self._low + 1.0)

    def _escape(self, packed: int) -> str:
        code = self._color_cache.get(packed)
        if code is not None:
            return code
        r = (packed >> 16) & 0xFF
        g = (packed >>  8) & 0xFF
        b =  packed        & 0xFF
        code = f"\x1b[38;2;{r};{g};{b}m"
        if len(self._color_cache) >= _MAX_CACHE:
            self._color_cache.clear()
        self._color_cache[packed] = code
        return code

    def render(self, frame: np.ndarray) -> str:
        rgb = as_rgb(frame)
        height, width = rgb.shape[:2]
        if height == 0 or width == 0:
            return ""

        if height > 32 and width > 32:
            low, high = self._contrast_window(luma(rgb[::4, ::4]))
        else:
            low, high = self._contrast_window(luma(rgb))

        span = max(float(high - low), 1.0)
        vals = np.arange(256, dtype=np.float32)
        norm = np.clip((vals - low) / span, 0.0, 1.0)
        if self.color:
            mapped = np.power(norm, np.float32(0.65))
            ramp = RAMP_ARRAY
            mask_val = 0x00F0F0F0 if width >= 200 else 0x00F8F8F8
        else:
            mapped = np.power(norm, np.float32(0.9))
            ramp = RAMP_BW_ARRAY

        lut = (mapped * np.float32(ramp.size - 1)).astype(np.intp)
        ramp_lut = ramp[lut]

        l_int = (
            (rgb[:, :, 0].astype(np.uint16) * 77
             + rgb[:, :, 1].astype(np.uint16) * 150
             + rgb[:, :, 2].astype(np.uint16) * 29) >> 8
        ).astype(np.uint8)
        glyphs = ramp_lut[l_int]

        if not self.color:
            return "\n".join("".join(row) for row in glyphs.tolist())

        packed = pack_rgb(rgb)
        masked = packed & mask_val
        cache = self._color_cache
        escape_fn = self._escape
        lines: list[str] = []
        for row in range(height):
            glyph_row = glyphs[row].tolist()
            mask_row = masked[row].tolist()
            color_row = packed[row].tolist()
            parts: list[str] = []
            app = parts.append
            start = 0
            curr_m = mask_row[0]
            for col in range(1, width):
                m = mask_row[col]
                if m != curr_m:
                    code = cache.get(curr_m)
                    if code is None:
                        code = escape_fn(color_row[start])
                        cache[curr_m] = code
                    app(code + "".join(glyph_row[start:col]))
                    start = col
                    curr_m = m
            code = cache.get(curr_m)
            if code is None:
                code = escape_fn(color_row[start])
                cache[curr_m] = code
            app(code + "".join(glyph_row[start:width]))
            app(_RESET)
            lines.append("".join(parts))
        return "\n".join(lines)
