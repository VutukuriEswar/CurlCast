from __future__ import annotations

import pytest

from curlcast.renderers import get_renderer

SIZES = [
    (1600, 900),
    (1600, 1200),
    (800, 800),
    (1080, 1920),
    (2560, 1080),
    (64, 48),
]

GRIDS = [(40, 23), (80, 24), (120, 50), (10, 5)]


@pytest.mark.parametrize("mode", ["hd", "ascii"])
@pytest.mark.parametrize("size", SIZES)
@pytest.mark.parametrize("grid", GRIDS)
def test_fit_stays_within_budget(mode: str, size: tuple[int, int], grid: tuple[int, int]) -> None:
    cols, rows = grid
    renderer = get_renderer(mode, width=cols, rows=rows)
    width, height = renderer.fit(*size)

    assert 1 <= width <= cols
    assert 1 <= height <= int(rows * renderer.PIXEL_ASPECT)


@pytest.mark.parametrize("mode", ["hd", "ascii"])
@pytest.mark.parametrize("size", SIZES)
def test_fit_preserves_source_aspect(mode: str, size: tuple[int, int]) -> None:
    renderer = get_renderer(mode, width=120, rows=60)
    width, height = renderer.fit(*size)
    expected = size[0] / size[1]
    assert abs((width / height) / expected - 1.0) < 0.06


def test_ascii_samples_one_pixel_row_per_character() -> None:
    assert get_renderer("ascii").PIXEL_ASPECT == 1.0


def test_hd_samples_two_pixel_rows_per_character() -> None:
    assert get_renderer("hd").PIXEL_ASPECT == 2.0


@pytest.mark.parametrize("mode", ["hd", "ascii"])
def test_rendered_line_count_fits_rows(mode: str, gradient) -> None:
    renderer = get_renderer(mode, width=120, rows=23)
    art = renderer.render_image(gradient.resize((1920, 1080)))
    assert 1 <= len(art.splitlines()) <= 23


def test_no_upscale_by_default_for_view(gradient) -> None:
    renderer = get_renderer("hd", width=100, rows=40)
    width, height = renderer.fit(*gradient.resize((32, 24)).size)
    assert width <= 32
    assert height <= 24


def test_upscale_fills_the_terminal() -> None:
    renderer = get_renderer("hd", width=100, rows=40)
    width, height = renderer.fit(32, 24, upscale=True)
    assert width > 32
    assert height <= 80


def test_pixel_dimensions_matches_aspect() -> None:
    from curlcast.renderers import get_renderer as get

    assert get("hd", width=80, rows=23).pixel_dimensions() == (80, 46)
    assert get("ascii", width=80, rows=23).pixel_dimensions() == (80, 23)
