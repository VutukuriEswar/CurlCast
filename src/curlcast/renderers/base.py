from __future__ import annotations

from abc import ABC, abstractmethod
from enum import Enum

import numpy as np
from PIL import Image

from curlcast.terminal import get_size


class RenderMode(str, Enum):
    ASCII = "ascii"


class BaseRenderer(ABC):
    PIXEL_ASPECT: float = 2.0

    def __init__(self, width: int = 0, color: bool = True, rows: int = 0) -> None:
        self._user_width = width
        self._user_rows = rows
        size = get_size()
        self.cols: int = width if width > 0 else max(size.columns - 1, 10)
        self.rows: int = rows if rows > 0 else max(size.rows - 1, 4)
        self.color: bool = color

    def refresh_size(self, max_cols: int = 0, max_rows: int = 0) -> bool:
        size = get_size()
        new_cols = self._user_width if self._user_width > 0 else max(size.columns - 1, 10)
        new_rows = self._user_rows if self._user_rows > 0 else max(size.rows - 1, 4)
        if max_cols > 0:
            new_cols = min(new_cols, max_cols)
        if max_rows > 0:
            new_rows = min(new_rows, max_rows)
        if new_cols != self.cols or new_rows != self.rows:
            self.cols = new_cols
            self.rows = new_rows
            return True
        return False

    @property
    def target_cols(self) -> int:
        return self.cols

    @property
    def target_rows(self) -> int:
        return self.rows

    def cell_aspect(self) -> float:
        ratio = self.cols / max(1, self.rows)
        if self.rows > 120 and ratio < 1.6:
            return max(0.5, min(self.PIXEL_ASPECT, ratio / (16.0 / 9.0)))
        return self.PIXEL_ASPECT

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
        width, height = self.fit(*rgb.size, upscale=upscale)
        if rgb.size == (width, height):
            return rgb
        return rgb.resize((width, height), Image.Resampling.LANCZOS)

    @abstractmethod
    def render(self, frame: np.ndarray) -> str:
        pass

    def render_frame(self, image: Image.Image) -> str:
        rgb = image if image.mode == "RGB" else image.convert("RGB")
        return self.render(np.asarray(rgb, dtype=np.uint8))

    def render_image(self, image: Image.Image, *, upscale: bool = False) -> str:
        return self.render_frame(self.resize_image(image, upscale=upscale))

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}(cols={self.cols}, rows={self.rows}, "
            f"color={self.color})"
        )
