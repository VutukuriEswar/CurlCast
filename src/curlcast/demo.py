from __future__ import annotations

import math
from collections.abc import Iterator
from enum import Enum

import numpy as np

from curlcast.player import Frame, PerfClock, render_loop
from curlcast.renderers.base import BaseRenderer
from curlcast.terminal import Screen


class DemoAnimation(str, Enum):
    PLASMA = "plasma"
    TORUS = "torus"


def _hsv_to_rgb(hue: np.ndarray, saturation: float, value: np.ndarray) -> np.ndarray:
    sector = np.floor(hue * 6.0)
    fraction = hue * 6.0 - sector
    sector = sector.astype(np.intp) % 6

    p = value * (1.0 - saturation)
    q = value * (1.0 - fraction * saturation)
    t = value * (1.0 - (1.0 - fraction) * saturation)

    red = np.choose(sector, [value, q, p, p, t, value])
    green = np.choose(sector, [t, value, value, q, p, p])
    blue = np.choose(sector, [p, p, t, value, value, q])
    return np.stack((red, green, blue), axis=-1)


def _rotate(
    x: np.ndarray, y: np.ndarray, z: np.ndarray, angle_x: float, angle_y: float
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    cos_x, sin_x = math.cos(angle_x), math.sin(angle_x)
    y, z = y * cos_x - z * sin_x, y * sin_x + z * cos_x
    cos_y, sin_y = math.cos(angle_y), math.sin(angle_y)
    x, z = x * cos_y + z * sin_y, -x * sin_y + z * cos_y
    return x, y, z


class DemoSource:
    def __init__(
        self,
        renderer: BaseRenderer,
        *,
        duration: float = 10.0,
        fps: float = 24.0,
        animation: DemoAnimation = DemoAnimation.PLASMA,
    ) -> None:
        self.fps = min(max(float(fps), 1.0), 60.0)
        self.duration = max(float(duration), 0.0)
        self.animation = animation

        width, height = renderer.pixel_dimensions()
        self.width = max(8, min(width, 400))
        self.height = max(4, min(height, 200))

        xs = np.linspace(0.0, 4.0 * math.pi, self.width, dtype=np.float32)
        ys = np.linspace(0.0, 4.0 * math.pi, self.height, dtype=np.float32)
        self._x, self._y = np.meshgrid(xs, ys)


        u_values = np.linspace(0.0, 2.0 * math.pi, 96, dtype=np.float32)
        v_values = np.linspace(0.0, 2.0 * math.pi, 40, dtype=np.float32)
        self._u, self._v = np.meshgrid(u_values, v_values)

    def frames(self) -> Iterator[Frame]:
        index = 0
        while True:
            timestamp = index / self.fps
            if self.duration > 0.0 and timestamp >= self.duration:
                return
            render = self._plasma if self.animation is DemoAnimation.PLASMA else self._torus
            yield render(timestamp), timestamp
            index += 1

    def _plasma(self, t: float) -> np.ndarray:
        x, y = self._x, self._y
        value = (
            np.sin(x + t * 1.1)
            + np.sin(y + t * 0.9)
            + np.sin((x + y + t) * 0.5)
            + np.sin(np.sqrt(x * x + y * y + 1e-6) * 2.0 - t * 1.8)
        )
        value = (value - value.min()) / (value.max() - value.min() + 1e-6)
        hue = (value * 0.75 + t * 0.06) % 1.0
        rgb = _hsv_to_rgb(hue, 0.9, 0.35 + 0.65 * value)
        return (rgb * 255.0).astype(np.uint8)

    def _torus(self, t: float) -> np.ndarray:
        width, height = self.width, self.height
        image = np.zeros((height, width, 3), dtype=np.uint8)

        ring, tube = 1.0, 0.42
        cos_v = np.cos(self._v)
        x = (ring + tube * cos_v) * np.cos(self._u)
        y = (ring + tube * cos_v) * np.sin(self._u)
        z = tube * np.sin(self._v)

        nx = cos_v * np.cos(self._u)
        ny = cos_v * np.sin(self._u)
        nz = np.sin(self._v)

        angle_x = 0.9 * t + 0.4
        angle_y = 1.2 * t
        x, y, z = _rotate(x, y, z, angle_x, angle_y)
        nx, ny, nz = _rotate(nx, ny, nz, angle_x, angle_y)

        scale = min(width, height) / 3.2
        screen_x = np.clip((x * scale + width * 0.5).astype(np.int32), 0, width - 1)
        screen_y = np.clip((-y * scale + height * 0.5).astype(np.int32), 0, height - 1)

        light = np.clip(nx * 0.42 + ny * 0.61 + nz * 0.67, 0.0, 1.0)
        hue = (0.56 + 0.22 * np.sin(self._u + t * 0.8) + 0.12 * np.sin(self._v * 2.0)) % 1.0
        colors = (_hsv_to_rgb(hue, 0.85, 0.16 + 0.84 * light) * 255.0).astype(np.uint8)

        order = np.argsort(z, axis=None)
        image[screen_y.ravel()[order], screen_x.ravel()[order]] = colors.reshape(-1, 3)[order]
        return image


def run_demo(
    renderer: BaseRenderer,
    *,
    duration: float = 10.0,
    fps: float = 24.0,
    animation: DemoAnimation = DemoAnimation.PLASMA,
) -> None:
    source = DemoSource(renderer, duration=duration, fps=fps, animation=animation)
    screen = Screen()
    clock = PerfClock()
    with screen:
        render_loop(
            source.frames(),
            renderer,
            screen,
            clock,
            source.fps,
            source_size=(source.width, source.height),
        )
