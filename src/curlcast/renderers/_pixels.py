"""Small NumPy helpers shared by the built-in renderers."""

from __future__ import annotations

from typing import cast

import numpy as np


def as_rgb(frame: np.ndarray) -> np.ndarray:
    """Coerce an arbitrary image array to contiguous ``(H, W, 3)`` uint8."""
    array = np.asarray(frame)
    if array.ndim == 2:
        array = np.repeat(array[:, :, None], 3, axis=2)
    elif array.ndim == 3 and array.shape[2] == 4:
        array = array[:, :, :3]
    if array.ndim != 3 or array.shape[2] != 3:
        raise ValueError(f"expected an (H, W, 3) RGB array, got shape {array.shape}")
    if array.dtype != np.uint8:
        array = np.clip(array, 0, 255).astype(np.uint8)
    return cast(np.ndarray, np.ascontiguousarray(array))


def luma(rgb: np.ndarray) -> np.ndarray:
    """Rec. 601 luminance as float32, shape ``(H, W)``."""
    weighted = (
        rgb[:, :, 0].astype(np.float32) * np.float32(0.299)
        + rgb[:, :, 1].astype(np.float32) * np.float32(0.587)
        + rgb[:, :, 2].astype(np.float32) * np.float32(0.114)
    ).astype(np.float32)
    return cast(np.ndarray, weighted)


def pack_rgb(rgb: np.ndarray) -> np.ndarray:
    """Pack RGB triples into ``0xRRGGBB`` uint32 values."""
    wide = rgb.astype(np.uint32)
    return (wide[:, :, 0] << 16) | (wide[:, :, 1] << 8) | wide[:, :, 2]
