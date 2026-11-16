from __future__ import annotations

import re

import numpy as np
import pytest
from PIL import Image

_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")


def strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text)


def gradient_image(width: int = 160, height: int = 120) -> Image.Image:
    """A deterministic RGB image with smooth horizontal and vertical ramps."""
    x = np.linspace(0, 255, width, dtype=np.uint8)
    y = np.linspace(0, 255, height, dtype=np.uint8)
    red, _ = np.meshgrid(x, y)
    green = np.flipud(red)
    blue = np.full_like(red, 128)
    rgb = np.stack((red, green, blue), axis=-1)
    return Image.fromarray(rgb, "RGB")


@pytest.fixture
def gradient() -> Image.Image:
    return gradient_image()
