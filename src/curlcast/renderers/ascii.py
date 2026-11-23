from __future__ import annotations

import numpy as np
from PIL import Image, ImageFilter, ImageOps

from curlcast.renderers._pixels import as_rgb, luma, pack_rgb
from curlcast.renderers.base import BaseRenderer
from curlcast.renderers.effects import (
    DitherMode,
    ShaderMode,
    apply_anaglyph,
    apply_dither,
    apply_shader,
)

RAMP = " `.-':_,^=;><+!rc*/z?sLTv)J7(|Fi{C}fI31tlu[neoZ5Yxjya]2ESwqkP6h9d4VpOGbUAKXHm8RD#$Bg0MNWQ%&@"

RAMP_BW = RAMP

RAMP_ARRAY = np.array(list(RAMP), dtype="<U1")
RAMP_BW_ARRAY = RAMP_ARRAY

_RESET     = "\x1b[0m"
_MAX_CACHE = 16_384


class AsciiRenderer(BaseRenderer):
    PIXEL_ASPECT: float = 2.0

    def __init__(
        self,
        width: int = 0,
        color: bool = False,
        rows: int = 0,
        shader: ShaderMode | str = ShaderMode.NONE,
        dither: DitherMode | str = DitherMode.NONE,
        anaglyph: bool = False,
        text: str | None = None,
    ) -> None:
        shader_enum = (
            shader if isinstance(shader, ShaderMode) else ShaderMode(str(shader).strip().lower())
        )
        dither_enum = (
            dither if isinstance(dither, DitherMode) else DitherMode(str(dither).strip().lower())
        )
        has_color = (
            color
            or bool(anaglyph)
            or shader_enum
            in (
                ShaderMode.AMBER,
                ShaderMode.GREEN,
                ShaderMode.GAMEBOY,
                ShaderMode.SYNTHWAVE,
            )
        )
        super().__init__(width=width, color=has_color, rows=rows)
        self.shader: ShaderMode = shader_enum
        self.dither: DitherMode = dither_enum
        self.anaglyph: bool = bool(anaglyph)
        self._prev_frame: np.ndarray | None = None
        self._low: float | None = None
        self._high: float | None = None
        self._color_cache: dict[int, str] = {}
        self._active_text: str | None = None
        self._semantic_ramp: np.ndarray | None = None
        if text:
            self.set_active_text(text)

    def set_active_text(self, text: str | None) -> None:
        clean = str(text).strip() if text else ""
        if clean != (self._active_text or ""):
            self._active_text = clean or None
            if clean:
                from curlcast.lyrics import build_semantic_ramp

                base = RAMP_ARRAY if self.color else RAMP_BW_ARRAY
                self._semantic_ramp = build_semantic_ramp(clean, base)
            else:
                self._semantic_ramp = None

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

    def render(
        self,
        frame: np.ndarray,
        *,
        glitch: bool = False,
        luma_boost: float = 0.0,
    ) -> str:
        rgb = as_rgb(frame)
        height, width = rgb.shape[:2]
        if height == 0 or width == 0:
            return ""

        if glitch and width > 2:
            rgb = rgb.copy()
            rgb[:, :-1, 0] = rgb[:, 1:, 0]
            rgb[:, 1:, 2] = rgb[:, :-1, 2]

        if self.anaglyph:
            rgb = apply_anaglyph(rgb, shift=max(1, width // 80))

        if self.shader != ShaderMode.NONE:
            rgb = apply_shader(rgb, self.shader, prev_frame=self._prev_frame)
            if self.shader == ShaderMode.CRT:
                self._prev_frame = rgb.copy()

        if height > 32 and width > 32:
            low, high = self._contrast_window(luma(rgb[::4, ::4]))
        else:
            low, high = self._contrast_window(luma(rgb))

        if luma_boost > 0.0:
            low = max(0.0, low - luma_boost * 25.0)
            high = min(255.0, high + luma_boost * 20.0)

        span = max(float(high - low), 1.0)
        vals = np.arange(256, dtype=np.float32)
        norm = np.clip((vals - low) / span, 0.0, 1.0)
        if self._semantic_ramp is not None:
            ramp = self._semantic_ramp
            mapped = np.power(norm, np.float32(0.8))
            mask_val = 0x00F0F0F0 if width >= 200 else 0x00F8F8F8
        elif self.color:
            mapped = np.power(norm, np.float32(0.65))
            ramp = RAMP_ARRAY
            mask_val = 0x00F0F0F0 if width >= 200 else 0x00F8F8F8
        else:
            mapped = np.power(norm, np.float32(0.68))
            ramp = RAMP_ARRAY

        lut = (mapped * np.float32(ramp.size - 1)).astype(np.intp)
        ramp_lut = ramp[lut]

        l_int = (
            (rgb[:, :, 0].astype(np.uint16) * 77
             + rgb[:, :, 1].astype(np.uint16) * 150
             + rgb[:, :, 2].astype(np.uint16) * 29) >> 8
        ).astype(np.uint8)

        if not self.color and height > 2 and width > 2:
            pad = np.pad(l_int, 1, mode="edge")
            lap = 4 * l_int.astype(np.int16) - pad[:-2, 1:-1] - pad[2:, 1:-1] - pad[1:-1, :-2] - pad[1:-1, 2:]
            l_int = np.clip(l_int.astype(np.int16) + (lap >> 3), 0, 255).astype(np.uint8)

        if self.dither != DitherMode.NONE:
            l_int = apply_dither(l_int, self.dither, num_levels=ramp.size)

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
