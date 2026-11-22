from __future__ import annotations

from pathlib import Path

from conftest import gradient_image
from PIL import Image
from typer.testing import CliRunner

from curlcast import __version__
from curlcast.cli import app

runner = CliRunner()


def test_version() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert f"curlcast {__version__}" in result.output


def test_no_arguments_prints_help() -> None:
    result = runner.invoke(app, [])
    assert result.exit_code == 0
    assert "Usage" in result.output and "view" in result.output


def test_view_renders_without_escape_codes(tmp_path: Path) -> None:
    path = tmp_path / "pic.png"
    gradient_image(80, 60).save(path)

    result = runner.invoke(
        app,
        ["view", str(path), "--width", "20", "--no-upscale"],
    )
    assert result.exit_code == 0, result.output
    lines = result.output.splitlines()
    assert 1 <= len(lines) <= 20
    assert all(len(line) <= 20 for line in lines)
    assert "\x1b[" not in result.output


def test_view_ascii_does_not_emit_block_glyphs(tmp_path: Path) -> None:
    path = tmp_path / "pic.png"
    gradient_image(60, 40).save(path)

    result = runner.invoke(app, ["view", str(path), "--mode", "ascii", "--width", "20"])
    assert result.exit_code == 0, result.output
    assert "▀" not in result.output


def test_view_colour_output_contains_truecolor(tmp_path: Path) -> None:
    path = tmp_path / "pic.png"
    gradient_image(40, 30).save(path)

    result = runner.invoke(app, ["view", str(path), "--width", "10", "--color"])
    assert result.exit_code == 0, result.output
    assert "\x1b[38;2;" in result.output


def test_view_once_flag(tmp_path: Path) -> None:
    path = tmp_path / "pic.png"
    gradient_image(40, 30).save(path)

    result = runner.invoke(app, ["view", str(path), "--once", "--width", "10"])
    assert result.exit_code == 0, result.output
    assert len(result.output.splitlines()) > 0


def test_view_rejects_missing_file(tmp_path: Path) -> None:
    result = runner.invoke(app, ["view", str(tmp_path / "nope.png")])
    assert result.exit_code == 1
    assert "file not found" in result.output.lower()


def test_view_rejects_unsupported_extension(tmp_path: Path) -> None:
    path = tmp_path / "notes.txt"
    path.write_text("hello")
    result = runner.invoke(app, ["view", str(path)])
    assert result.exit_code == 1
    assert "unsupported file type" in result.output.lower()


def test_play_rejects_missing_file(tmp_path: Path) -> None:
    result = runner.invoke(app, ["play", str(tmp_path / "nope.mp4")])
    assert result.exit_code == 1
    assert "file not found" in result.output.lower()


def test_play_rejects_invalid_fps(tmp_path: Path) -> None:
    path = tmp_path / "clip.mp4"
    path.write_bytes(b"fake")
    result = runner.invoke(app, ["play", str(path), "--fps", "0"])
    assert result.exit_code != 0


def test_demo_runs_and_restores_the_cursor() -> None:
    result = runner.invoke(
        app,
        ["demo", "--duration", "0.15", "--width", "24", "--fps", "30", "--mode", "ascii"],
    )
    assert result.exit_code == 0, result.output
    assert "\x1b[?25l" in result.output
    assert result.output.rstrip().endswith("\x1b[?25h")


def test_play_gif_end_to_end(tmp_path: Path) -> None:
    path = tmp_path / "tiny.gif"
    frames = [Image.new("RGB", (16, 12), (index * 60, 20, 200)) for index in range(2)]
    frames[0].save(path, save_all=True, append_images=frames[1:], duration=[50, 50], loop=0)

    result = runner.invoke(
        app, ["play", str(path), "--no-audio", "--width", "16"]
    )
    assert result.exit_code == 0, result.output
    assert "\x1b[?25l" in result.output
    assert "\x1b[?25h" in result.output
