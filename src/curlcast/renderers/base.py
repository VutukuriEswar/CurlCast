from __future__ import annotations

from abc import ABC, abstractmethod
from enum import Enum

import numpy as np
from PIL import Image

from curlcast.terminal import get_size


class RenderMode(str, Enum):
    HD = "hd"
    ASCII = "ascii"


class BaseRenderer(ABC):
    PIXEL_ASPECT: float = 2.0

    def __init__(self, width: int = 0, color: bool = True, rows: int = 0) -> None:
        size = get_size()
        self.cols: int = width if width > 0 else max(size.columns - 1, 10)
        self.rows: int = rows if rows > 0 else max(size.rows - 1, 4)
        self.color: bool = color

    @property
    def target_cols(self) -> int:
        return self.cols

    @property
    def target_rows(self) -> int:
        return self.rows

    def fit(self, src_w: int, src_h: int, *, upscale: bool = False) -> tuple[int, int]:
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
        height = max(1, int(round(self.rows * self.PIXEL_ASPECT)))
        return self.cols, height

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
