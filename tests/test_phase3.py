from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from PIL import Image
from typer.testing import CliRunner

from curlcast.cli import app
from curlcast.renderers.normal import Flashlight, compute_normals


def test_compute_normals_flat():
    flat = np.full((20, 20), 128, dtype=np.uint8)
    normals = compute_normals(flat)
    assert normals.shape == (20, 20, 3)
    assert np.allclose(normals[..., 0], 0.0, atol=1e-3)
    assert np.allclose(normals[..., 1], 0.0, atol=1e-3)
    assert np.allclose(normals[..., 2], 1.0, atol=1e-3)


def test_compute_normals_gradient():
    grad = np.linspace(0, 255, 30, dtype=np.float32)[None, :].repeat(20, axis=0)
    normals = compute_normals(grad)
    assert normals.shape == (20, 30, 3)
    mags = np.linalg.norm(normals, axis=-1)
    assert np.allclose(mags, 1.0, atol=1e-3)
    assert np.any(np.abs(normals[..., 0]) > 0.05)


def test_compute_normals_invalid():
    with pytest.raises(ValueError, match="2D array"):
        compute_normals(np.zeros((10, 10, 3)))


def test_flashlight_movement_and_sweep():
    fl = Flashlight(x=0.5, y=0.5, radius=0.3, ambient=0.2, auto_sweep=True)
    assert fl.x == 0.5
    assert fl.y == 0.5

    fl.move(0.1, -0.2)
    assert np.isclose(fl.x, 0.6)
    assert np.isclose(fl.y, 0.3)

    fl.set_position(0.8, 0.9)
    assert np.isclose(fl.x, 0.8)
    assert np.isclose(fl.y, 0.9)

    fl_auto = Flashlight(auto_sweep=True)
    fl_auto.update_time(1.0)
    assert not np.isclose(fl_auto.x, 0.5) or not np.isclose(fl_auto.y, 0.5)


def test_flashlight_apply_light():
    fl = Flashlight(x=0.5, y=0.5, radius=0.3, ambient=0.1)
    img = np.full((40, 40, 3), 200, dtype=np.uint8)
    lit = fl.apply_light(img)

    assert lit.shape == img.shape
    assert lit.dtype == img.dtype

    center_val = np.mean(lit[20, 20])
    corner_val = np.mean(lit[0, 0])
    assert center_val > corner_val


def test_cli_flashlight_flags(tmp_path: Path):
    runner = CliRunner()
    img_path = tmp_path / "test.png"
    im = Image.new("RGB", (40, 20), color=(120, 140, 160))
    im.save(img_path)

    res_flash = runner.invoke(app, ["view", str(img_path), "--flashlight", "--once"])
    assert res_flash.exit_code == 0
    assert len(res_flash.output) > 0

    gif_path = tmp_path / "test.gif"
    frames = [Image.new("RGB", (16, 12), (100, 20, 200))]
    frames[0].save(gif_path, save_all=True, duration=[50], loop=0)

    res_play_flash = runner.invoke(
        app,
        ["play", str(gif_path), "--no-audio", "--width", "16", "--flashlight"],
    )
    assert res_play_flash.exit_code == 0
