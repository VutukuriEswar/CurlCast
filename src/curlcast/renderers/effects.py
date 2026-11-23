from __future__ import annotations

from enum import Enum
from typing import cast

import numpy as np
from PIL import Image


class ShaderMode(str, Enum):
    NONE = "none"
    CRT = "crt"
    AMBER = "amber"
    GREEN = "green"
    GAMEBOY = "gameboy"
    SYNTHWAVE = "synthwave"


class DitherMode(str, Enum):
    NONE = "none"
    BAYER = "bayer"
    FLOYD = "floyd"


_BAYER_8X8 = (
    np.array(
        [
            [0, 32, 8, 40, 2, 34, 10, 42],
            [48, 16, 56, 24, 50, 18, 58, 26],
            [12, 44, 4, 36, 14, 46, 6, 38],
            [60, 28, 52, 20, 62, 30, 54, 22],
            [3, 35, 11, 43, 1, 33, 9, 41],
            [51, 19, 59, 27, 49, 17, 57, 25],
            [15, 47, 7, 39, 13, 45, 5, 37],
            [63, 31, 55, 23, 61, 29, 53, 21],
        ],
        dtype=np.float32,
    )
    / 64.0
    - 0.5
) * 36.0


def _build_amber_lut() -> np.ndarray:
    t = np.linspace(0.0, 1.0, 256, dtype=np.float32)
    r = np.clip(t * 270.0, 0.0, 255.0)
    g = np.clip(t * 185.0, 0.0, 255.0)
    b = np.clip((t - 0.75) * 4.0 * 160.0, 0.0, 160.0)
    return np.stack([r, g, b], axis=-1).astype(np.uint8)


def _build_green_lut() -> np.ndarray:
    t = np.linspace(0.0, 1.0, 256, dtype=np.float32)
    r = np.clip((t - 0.7) * 3.33 * 200.0, 0.0, 200.0)
    g = np.clip(t * 260.0, 0.0, 255.0)
    b = np.clip((t - 0.7) * 3.33 * 200.0, 0.0, 200.0)
    return np.stack([r, g, b], axis=-1).astype(np.uint8)


def _build_gameboy_lut() -> np.ndarray:
    pal = np.array(
        [[15, 56, 15], [48, 98, 48], [139, 172, 15], [155, 188, 15]], dtype=np.uint8
    )
    idx = np.clip(np.arange(256) // 64, 0, 3)
    return pal[idx]


def _build_synthwave_lut() -> np.ndarray:
    pts = np.array(
        [
            [13, 2, 33],
            [84, 19, 136],
            [255, 0, 127],
            [0, 240, 255],
            [245, 250, 255],
        ],
        dtype=np.float32,
    )
    x_pts = np.array([0, 64, 140, 220, 255], dtype=np.float32)
    lut = np.zeros((256, 3), dtype=np.uint8)
    for c in range(3):
        lut[:, c] = np.clip(
            np.interp(np.arange(256), x_pts, pts[:, c]), 0, 255
        ).astype(np.uint8)
    return lut


AMBER_LUT = _build_amber_lut()
GREEN_LUT = _build_green_lut()
GAMEBOY_LUT = _build_gameboy_lut()
SYNTHWAVE_LUT = _build_synthwave_lut()


def apply_shader(
    rgb: np.ndarray,
    mode: ShaderMode | str,
    prev_frame: np.ndarray | None = None,
) -> np.ndarray:
    mode_str = mode.value if isinstance(mode, ShaderMode) else str(mode).strip().lower()
    if mode_str == ShaderMode.NONE.value or not mode_str:
        return rgb

    if mode_str == ShaderMode.CRT.value:
        out = rgb.copy()
        if prev_frame is not None and prev_frame.shape == out.shape:
            out = np.maximum(out, (prev_frame.astype(np.uint16) * 40) >> 8)
        out[1::2] = (out[1::2].astype(np.uint16) * 179) >> 8
        return cast(np.ndarray, out)

    l_int = (
        (
            rgb[:, :, 0].astype(np.uint16) * 77
            + rgb[:, :, 1].astype(np.uint16) * 150
            + rgb[:, :, 2].astype(np.uint16) * 29
        )
        >> 8
    ).astype(np.uint8)

    if mode_str == ShaderMode.AMBER.value:
        return cast(np.ndarray, AMBER_LUT[l_int])
    if mode_str == ShaderMode.GREEN.value:
        return cast(np.ndarray, GREEN_LUT[l_int])
    if mode_str == ShaderMode.GAMEBOY.value:
        return cast(np.ndarray, GAMEBOY_LUT[l_int])
    if mode_str == ShaderMode.SYNTHWAVE.value:
        return cast(np.ndarray, SYNTHWAVE_LUT[l_int])

    return rgb


def apply_dither(
    luma_img: np.ndarray,
    mode: DitherMode | str,
    num_levels: int = 10,
) -> np.ndarray:
    mode_str = mode.value if isinstance(mode, DitherMode) else str(mode).strip().lower()
    if mode_str == DitherMode.NONE.value or not mode_str:
        return luma_img

    if mode_str == DitherMode.BAYER.value:
        h, w = luma_img.shape[:2]
        reps_y = (h // 8) + 1
        reps_x = (w // 8) + 1
        tiled = np.tile(_BAYER_8X8, (reps_y, reps_x))[:h, :w]
        return cast(
            np.ndarray,
            np.clip(luma_img.astype(np.float32) + tiled, 0.0, 255.0).astype(np.uint8),
        )

    if mode_str == DitherMode.FLOYD.value:
        pil_img = Image.fromarray(luma_img)
        quant = pil_img.quantize(
            colors=max(2, min(num_levels, 256)), dither=Image.Dither.FLOYDSTEINBERG
        )
        arr = np.asarray(quant, dtype=np.float32)
        return cast(
            np.ndarray,
            np.clip(arr * (255.0 / max(1, num_levels - 1)), 0.0, 255.0).astype(np.uint8),
        )

    return luma_img


def apply_anaglyph(rgb: np.ndarray, shift: int = 1) -> np.ndarray:
    h, w = rgb.shape[:2]
    l_int = (
        (
            rgb[:, :, 0].astype(np.uint16) * 77
            + rgb[:, :, 1].astype(np.uint16) * 150
            + rgb[:, :, 2].astype(np.uint16) * 29
        )
        >> 8
    ).astype(np.uint8)

    left = np.zeros_like(l_int)
    right = np.zeros_like(l_int)

    if shift > 0 and w > shift:
        left[:, shift:] = l_int[:, :-shift]
        left[:, :shift] = l_int[:, :1]
        right[:, :-shift] = l_int[:, shift:]
        right[:, -shift:] = l_int[:, -1:]
    else:
        left = l_int
        right = l_int

    out = np.zeros((h, w, 3), dtype=np.uint8)
    out[:, :, 0] = left
    out[:, :, 1] = right
    out[:, :, 2] = right
    return out
