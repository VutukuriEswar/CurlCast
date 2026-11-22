from __future__ import annotations

import numpy as np
import pytest
from conftest import gradient_image, strip_ansi
from PIL import Image

from curlcast.renderers import get_renderer
from curlcast.renderers.ascii import RAMP, RAMP_ARRAY


@pytest.mark.parametrize("color", [True, False])
def test_every_line_has_the_same_visible_width(color: bool, gradient) -> None:
    renderer = get_renderer("ascii", width=40, rows=20, color=color)
    art = renderer.render_image(gradient.resize((160, 120)))
    lines = art.splitlines()
    assert lines
    widths = {len(strip_ansi(line)) for line in lines}
    assert len(widths) == 1, f"ragged art: widths={sorted(widths)}"
    assert widths.pop() <= 40


def test_colour_mode_emits_truecolor(gradient) -> None:
    renderer = get_renderer("ascii", width=30, rows=12, color=True)
    art = renderer.render_image(gradient)
    assert "\x1b[38;2;" in art
    assert all(line.endswith("\x1b[0m") for line in art.splitlines())


def test_no_color_emits_no_escape_sequences(gradient) -> None:
    renderer = get_renderer("ascii", width=30, rows=12, color=False)
    art = renderer.render_image(gradient)
    assert "\x1b[" not in art


def test_odd_and_tiny_sizes_do_not_crash() -> None:
    for size in ((63, 63), (1, 1), (1, 200), (200, 1), (3, 5)):
        image = gradient_image(*size)
        art = get_renderer("ascii", width=30, rows=12).render_image(image)
        assert art
        assert all(len(strip_ansi(line)) <= 30 for line in art.splitlines())


def test_accepts_rgba_and_grayscale() -> None:
    rgba = gradient_image(40, 30).convert("RGBA")
    grayscale = gradient_image(40, 30).convert("L")
    for image in (rgba, grayscale):
        art = get_renderer("ascii", width=20, rows=10).render_frame(image)
        assert art


def test_ascii_ramp_has_unique_printable_chars_dark_to_bright() -> None:
    assert len(RAMP) >= 2
    assert len(set(RAMP)) == len(RAMP)
    assert RAMP[0] == " "
    assert RAMP[-1] == "@"


def test_ascii_contrast_makes_dark_frames_legible() -> None:
    dark = np.full((40, 60, 3), 12, dtype=np.uint8)
    dark[10:30, 10:50] = 40
    art = get_renderer("ascii", width=60, rows=40, color=False).render(
        np.asarray(dark)
    )
    glyphs = {char for char in art if char != "\n"}
    assert " " in glyphs
    assert "@" in glyphs


def test_contrast_window_is_smoothed_across_frames() -> None:
    renderer = get_renderer("ascii", width=20, rows=10, color=False)
    renderer.render(np.full((10, 20, 3), 20, dtype=np.uint8))
    first = (renderer._low, renderer._high)
    renderer.render(np.full((10, 20, 3), 240, dtype=np.uint8))
    second = (renderer._low, renderer._high)
    assert second != first
    renderer.reset_contrast()
    assert renderer._low is None and renderer._high is None


def test_registry_roundtrip() -> None:
    from curlcast.renderers import available_modes
    from curlcast.renderers import get_renderer as get

    assert available_modes() == ["ascii"]
    with pytest.raises(ValueError, match="unknown render mode"):
        get("braille")
    with pytest.raises(ValueError, match="unknown render mode"):
        get("hd")


def test_render_frame_uses_pil_image(gradient) -> None:
    renderer = get_renderer("ascii", width=20, rows=10)
    art = renderer.render_frame(Image.fromarray(np.asarray(gradient)))
    assert art
