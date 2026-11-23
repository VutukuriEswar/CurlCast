from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image
from typer.testing import CliRunner

from curlcast.cli import app
from curlcast.lyrics import LyricEngine, build_semantic_ramp
from curlcast.renderers.ascii import AsciiRenderer


def test_lyric_engine_empty():
    engine = LyricEngine()
    assert not engine.has_content()
    assert engine.get_line(0.0) is None


def test_lyric_engine_static():
    engine = LyricEngine("Never Gonna Give You Up")
    assert engine.has_content()
    assert engine.get_line(0.0) == "Never Gonna Give You Up"
    assert engine.get_line(100.0) == "Never Gonna Give You Up"


def test_lyric_engine_lrc(tmp_path: Path):
    lrc_content = (
        "[00:01.00]First line\n"
        "[00:05.50]Second line\n"
        "[00:10.00]Third line\n"
    )
    p = tmp_path / "song.lrc"
    p.write_text(lrc_content, encoding="utf-8")

    engine = LyricEngine(p)
    assert engine.has_content()
    assert engine.get_line(0.5) == "First line"
    assert engine.get_line(1.0) == "First line"
    assert engine.get_line(3.0) == "First line"
    assert engine.get_line(5.5) == "Second line"
    assert engine.get_line(10.0) == "Third line"
    assert engine.get_line(12.0) == "Third line"
    assert engine.get_line(20.0) == "Third line"


def test_lyric_engine_srt(tmp_path: Path):
    srt_content = (
        "1\n"
        "00:00:01,000 --> 00:00:04,000\n"
        "Hello world\n\n"
        "2\n"
        "00:00:05.500 --> 00:00:08.500\n"
        "Subtitle two\n"
    )
    p = tmp_path / "subs.srt"
    p.write_text(srt_content, encoding="utf-8")

    engine = LyricEngine(p)
    assert engine.has_content()
    assert engine.get_line(0.0) == "Hello world"
    assert engine.get_line(2.0) == "Hello world"
    assert engine.get_line(4.5) == "Hello world"
    assert engine.get_line(6.0) == "Subtitle two"
    assert engine.get_line(9.0) == "Subtitle two"


def test_build_semantic_ramp():
    default_ramp = np.array(list(" .:-=+*#%@"), dtype="<U1")
    res_empty = build_semantic_ramp("", default_ramp)
    assert np.array_equal(res_empty, default_ramp)

    res_short = build_semantic_ramp("ab", default_ramp)
    assert len(res_short) == 3
    assert res_short[0] == " "

    res = build_semantic_ramp("CURLCAST TERMINAL ENGINE 123", default_ramp)
    assert len(res) > 3
    assert res[0] == " "


def test_ascii_renderer_semantic_text(gradient):
    renderer = AsciiRenderer(width=40, rows=20, text="TEST STRING")
    out = renderer.render(gradient)
    assert len(out) > 0
    assert " " in out or "T" in out or "E" in out or "S" in out


def test_cli_text_flags(tmp_path: Path):
    runner = CliRunner()
    img_path = tmp_path / "test.png"
    im = Image.new("RGB", (40, 20), color=(100, 150, 200))
    im.save(img_path)

    res_view = runner.invoke(app, ["view", str(img_path), "--text", "CUSTOM WORDS"])
    assert res_view.exit_code == 0

    gif_path = tmp_path / "test.gif"
    frames = [Image.new("RGB", (16, 12), (100, 20, 200))]
    frames[0].save(gif_path, save_all=True, duration=[50], loop=0)

    lrc_file = tmp_path / "test.lrc"
    lrc_file.write_text("[00:00.00]CURLCAST LYRIC\n", encoding="utf-8")
    res_play = runner.invoke(
        app,
        [
            "play",
            str(gif_path),
            "--no-audio",
            "--width",
            "16",
            "--text",
            str(lrc_file),
        ],
    )
    assert res_play.exit_code == 0
