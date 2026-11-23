from __future__ import annotations

import numpy as np
from conftest import gradient_image
from typer.testing import CliRunner

from curlcast.cli import app
from curlcast.renderers import DitherMode, ShaderMode, get_renderer
from curlcast.renderers.effects import (
    apply_anaglyph,
    apply_dither,
    apply_shader,
)

runner = CliRunner()


def test_shader_modes_exist() -> None:
    assert ShaderMode.NONE.value == "none"
    assert ShaderMode.CRT.value == "crt"
    assert ShaderMode.AMBER.value == "amber"
    assert ShaderMode.GREEN.value == "green"
    assert ShaderMode.GAMEBOY.value == "gameboy"
    assert ShaderMode.SYNTHWAVE.value == "synthwave"


def test_dither_modes_exist() -> None:
    assert DitherMode.NONE.value == "none"
    assert DitherMode.BAYER.value == "bayer"
    assert DitherMode.FLOYD.value == "floyd"


def test_apply_shader_none_leaves_image_unmodified() -> None:
    arr = np.full((20, 20, 3), 120, dtype=np.uint8)
    res = apply_shader(arr, ShaderMode.NONE)
    assert np.array_equal(res, arr)


def test_apply_shader_crt_dims_alternate_lines() -> None:
    arr = np.full((20, 20, 3), 200, dtype=np.uint8)
    res = apply_shader(arr, ShaderMode.CRT)
    assert np.array_equal(res[0], arr[0])
    assert res[1, 0, 0] < res[0, 0, 0]


def test_apply_shader_crt_blends_prev_frame() -> None:
    arr = np.zeros((10, 10, 3), dtype=np.uint8)
    prev = np.full((10, 10, 3), 200, dtype=np.uint8)
    res = apply_shader(arr, ShaderMode.CRT, prev_frame=prev)
    assert res[0, 0, 0] > 0


def test_apply_shader_amber_maps_to_warm_palette() -> None:
    arr = np.zeros((10, 10, 3), dtype=np.uint8)
    arr[:, :] = [128, 128, 128]
    res = apply_shader(arr, ShaderMode.AMBER)
    assert res.shape == (10, 10, 3)
    assert res[0, 0, 0] >= res[0, 0, 1] >= res[0, 0, 2]


def test_apply_shader_green_maps_to_phosphor_palette() -> None:
    arr = np.zeros((10, 10, 3), dtype=np.uint8)
    arr[:, :] = [128, 128, 128]
    res = apply_shader(arr, ShaderMode.GREEN)
    assert res.shape == (10, 10, 3)
    assert res[0, 0, 1] > res[0, 0, 0]
    assert res[0, 0, 1] > res[0, 0, 2]


def test_apply_shader_gameboy_uses_four_discrete_levels() -> None:
    ramp = np.arange(256, dtype=np.uint8).reshape(16, 16)
    arr = np.stack([ramp, ramp, ramp], axis=-1)
    res = apply_shader(arr, ShaderMode.GAMEBOY)
    unique_colors = np.unique(res.reshape(-1, 3), axis=0)
    assert len(unique_colors) <= 4


def test_apply_shader_synthwave_produces_neon_gradients() -> None:
    ramp = np.arange(256, dtype=np.uint8).reshape(16, 16)
    arr = np.stack([ramp, ramp, ramp], axis=-1)
    res = apply_shader(arr, ShaderMode.SYNTHWAVE)
    assert res.shape == (16, 16, 3)
    assert not np.array_equal(res[0, 0], res[15, 15])


def test_apply_dither_bayer_adds_spatial_frequency() -> None:
    luma = np.full((32, 32), 128, dtype=np.uint8)
    dithered = apply_dither(luma, DitherMode.BAYER)
    assert dithered.shape == (32, 32)
    assert len(np.unique(dithered)) > 1


def test_apply_dither_floyd_quantizes_and_diffuses() -> None:
    luma = np.linspace(0, 255, 32 * 32, dtype=np.uint8).reshape(32, 32)
    dithered = apply_dither(luma, DitherMode.FLOYD, num_levels=10)
    assert dithered.shape == (32, 32)
    assert len(np.unique(dithered)) <= 10


def test_apply_anaglyph_creates_red_cyan_fringes() -> None:
    arr = np.zeros((20, 40, 3), dtype=np.uint8)
    arr[:, 20:] = 255
    res = apply_anaglyph(arr, shift=2)
    assert res.shape == (20, 40, 3)
    assert res[10, 18, 0] != res[10, 18, 1]


def test_renderer_with_amber_shader_enables_color() -> None:
    renderer = get_renderer("ascii", width=20, rows=10, shader="amber")
    assert renderer.color is True
    art = renderer.render_image(gradient_image(40, 30))
    assert "\x1b[38;2;" in art


def test_renderer_with_dither_and_shader() -> None:
    renderer = get_renderer(
        "ascii", width=30, rows=15, shader="synthwave", dither="bayer"
    )
    art = renderer.render_image(gradient_image(60, 40))
    assert art
    assert "\x1b[38;2;" in art


def test_renderer_with_anaglyph_3d() -> None:
    renderer = get_renderer("ascii", width=30, rows=15, anaglyph=True)
    assert renderer.color is True
    art = renderer.render_image(gradient_image(60, 40))
    assert art
    assert "\x1b[38;2;" in art


def test_cli_view_with_shader_and_dither_options(tmp_path) -> None:
    img_path = tmp_path / "test.png"
    gradient_image(40, 30).save(img_path)
    result = runner.invoke(
        app,
        [
            "view",
            str(img_path),
            "--shader",
            "amber",
            "--dither",
            "bayer",
            "--once",
            "--width",
            "20",
        ],
    )
    assert result.exit_code == 0
    assert "\x1b[38;2;" in result.output


def test_cli_view_with_anaglyph(tmp_path) -> None:
    img_path = tmp_path / "test_3d.png"
    gradient_image(40, 30).save(img_path)
    result = runner.invoke(
        app,
        [
            "view",
            str(img_path),
            "--3d",
            "--width",
            "20",
            "--once",
        ],
    )
    assert result.exit_code == 0
