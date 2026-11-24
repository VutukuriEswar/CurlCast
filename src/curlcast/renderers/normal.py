from __future__ import annotations

from typing import cast

import numpy as np


def compute_normals(luma: np.ndarray, strength: float = 1.5) -> np.ndarray:
    if luma.ndim != 2:
        raise ValueError("luma must be 2D array")
    h, w = luma.shape
    if h < 2 or w < 2:
        normals = np.zeros((h, w, 3), dtype=np.float32)
        normals[..., 2] = 1.0
        return normals

    luma_f = luma.astype(np.float32)
    if luma_f.max() > 1.0:
        luma_f /= 255.0

    pad = np.pad(luma_f, 1, mode="edge")
    gx = (
        -pad[:-2, :-2] + pad[:-2, 2:]
        - 2.0 * pad[1:-1, :-2] + 2.0 * pad[1:-1, 2:]
        - pad[2:, :-2] + pad[2:, 2:]
    ) * (strength / 8.0)

    gy = (
        -pad[:-2, :-2] - 2.0 * pad[:-2, 1:-1] - pad[:-2, 2:]
        + pad[2:, :-2] + 2.0 * pad[2:, 1:-1] + pad[2:, 2:]
    ) * (strength / 8.0)

    gz = np.ones_like(gx, dtype=np.float32)
    norm = np.sqrt(gx * gx + gy * gy + gz * gz)
    norm = np.maximum(norm, 1e-6)

    nx = -gx / norm
    ny = -gy / norm
    nz = gz / norm
    return np.stack([nx, ny, nz], axis=-1)


class Flashlight:
    def __init__(
        self,
        x: float = 0.5,
        y: float = 0.5,
        z: float = 0.5,
        radius: float = 0.4,
        ambient: float = 0.15,
        auto_sweep: bool = False,
    ) -> None:
        self.x = float(np.clip(x, 0.0, 1.0))
        self.y = float(np.clip(y, 0.0, 1.0))
        self.z = max(0.1, float(z))
        self.radius = max(0.05, float(radius))
        self.ambient = float(np.clip(ambient, 0.0, 1.0))
        self.auto_sweep = auto_sweep
        self._manual = False

    def move(self, dx: float, dy: float) -> None:
        self._manual = True
        self.x = float(np.clip(self.x + dx, 0.0, 1.0))
        self.y = float(np.clip(self.y + dy, 0.0, 1.0))

    def set_position(self, x: float, y: float) -> None:
        self._manual = True
        self.x = float(np.clip(x, 0.0, 1.0))
        self.y = float(np.clip(y, 0.0, 1.0))

    def update_time(self, t: float) -> None:
        if self.auto_sweep and not self._manual:
            self.x = 0.5 + 0.35 * float(np.sin(t * 1.5))
            self.y = 0.5 + 0.25 * float(np.cos(t * 2.1))

    def apply_light(
        self,
        rgb: np.ndarray,
        normals: np.ndarray | None = None,
    ) -> np.ndarray:
        h, w = rgb.shape[:2]
        if normals is None:
            if rgb.ndim == 3 and rgb.shape[2] >= 3:
                luma = (
                    0.299 * rgb[..., 0].astype(np.float32)
                    + 0.587 * rgb[..., 1].astype(np.float32)
                    + 0.114 * rgb[..., 2].astype(np.float32)
                )
            else:
                luma = rgb.astype(np.float32)
            normals = compute_normals(luma)

        ys = np.linspace(0.0, 1.0, h, dtype=np.float32)[:, None]
        xs = np.linspace(0.0, 1.0, w, dtype=np.float32)[None, :]

        dx = self.x - xs
        dy = self.y - ys
        dz = self.z

        dist_sq = dx * dx + dy * dy
        dist_3d = np.sqrt(dist_sq + dz * dz)

        lx = dx / dist_3d
        ly = dy / dist_3d
        lz = dz / dist_3d

        dot = normals[..., 0] * lx + normals[..., 1] * ly + normals[..., 2] * lz
        diffuse = np.maximum(0.0, dot)

        beam = np.exp(-dist_sq / (2.0 * self.radius * self.radius))
        light_mult = self.ambient + (1.0 - self.ambient) * beam * (0.35 + 0.65 * diffuse)

        if rgb.ndim == 3:
            light_mult = light_mult[..., None]

        lit = rgb.astype(np.float32) * light_mult
        return cast(np.ndarray, np.clip(lit, 0.0, 255.0).astype(rgb.dtype))
