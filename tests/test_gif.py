from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from curlcast.player import GifSource
from curlcast.renderers import get_renderer


def make_gif(path: Path, sizes: tuple[int, int] = (24, 16)) -> Path:
    frames = [
        Image.new("RGB", sizes, (30 * index, 60, 200 - 30 * index)) for index in range(3)
    ]
    frames[0].save(
        path,
        save_all=True,
        append_images=frames[1:],
        duration=[100, 200, 300],
        loop=0,
    )
    return path


def test_gif_frames_are_sized_and_timestamped(tmp_path: Path) -> None:
    path = make_gif(tmp_path / "anim.gif")
    renderer = get_renderer("hd", width=10, rows=6)
    source = GifSource(path, renderer)
    frames = list(source.frames())

    assert len(frames) == 3
    expected = renderer.fit(24, 16)
    for frame, _ in frames:
        assert frame.shape[:2] == (expected[1], expected[0])
        assert frame.dtype == np.uint8

    timestamps = [round(ts, 3) for _, ts in frames]
    assert timestamps == [0.0, 0.1, 0.3]


def test_gif_with_broken_durations_is_clamped(tmp_path: Path) -> None:
    path = tmp_path / "fast.gif"
    frames = [Image.new("RGB", (16, 16), (index * 40, 0, 0)) for index in range(2)]
    frames[0].save(path, save_all=True, append_images=frames[1:], duration=[0, 0], loop=0)

    values = [ts for _, ts in GifSource(path, get_renderer("hd", width=8, rows=4)).frames()]
    assert values[0] == 0.0
    assert values[1] == pytest.approx(0.08)


def test_single_frame_gif(tmp_path: Path) -> None:
    path = tmp_path / "single.gif"
    Image.new("RGB", (16, 16), (10, 20, 30)).save(path)
    frames = list(GifSource(path, get_renderer("ascii", width=8, rows=4)).frames())
    assert len(frames) == 1
