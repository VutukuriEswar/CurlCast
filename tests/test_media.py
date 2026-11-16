from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from curlcast.ffmpeg import MediaError, ffmpeg_exe, parse_probe, probe_media
from curlcast.player import FFmpegSource
from curlcast.renderers import get_renderer

SAMPLE_PROBE = """\
ffmpeg version 7.0 Copyright (c) 2000-2024 the FFmpeg developers
  Duration: 00:00:05.00, start: 0.000000, bitrate: 3189 kb/s
  Stream #0:0[0x1](und): Video: h264 (High) (avc1 / 0x31637661), yuv420p, \
1280x720 [SAR 1:1 DAR 16:9], 3189 kb/s, 30 fps, 30 tbr, 15360 tbn
  Stream #0:1[0x2](und): Audio: aac (LC) (mp4a / 0x6134706D), 48000 Hz, stereo, fltp, 128 kb/s
"""


def test_parses_geometry_rate_duration_and_audio() -> None:
    info = parse_probe(SAMPLE_PROBE)
    assert info.width == 1280
    assert info.height == 720
    assert info.fps == 30.0
    assert info.duration == 5.0
    assert info.has_audio is True


def test_detects_missing_audio_stream() -> None:
    silent = "\n".join(line for line in SAMPLE_PROBE.splitlines() if "Audio:" not in line)
    assert parse_probe(silent).has_audio is False


def test_rotation_swaps_displayed_geometry() -> None:
    portrait = """
    Stream #0:0(und): Video: h264, yuv420p, 1920x1080, 30 fps
    Side data:
      displaymatrix: rotation of -90.00 degrees
    """
    info = parse_probe(portrait)
    assert (info.width, info.height) == (1080, 1920)


def test_legacy_rotate_metadata_is_honoured() -> None:
    info = parse_probe(
        "Stream #0:0: Video: h264, yuv420p, 1920x1080, 25 fps\n"
        "    rotate          : 90\n"
    )
    assert (info.width, info.height) == (1080, 1920)


def test_probe_without_video_raises(tmp_path: Path) -> None:
    path = tmp_path / "notes.mp4"
    path.write_bytes(b"not a video")
    with pytest.raises(MediaError):
        probe_media(path)


@pytest.fixture(scope="module")
def tiny_clip(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("media") / "clip.mp4"
    cmd = [
        ffmpeg_exe(),
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "lavfi",
        "-i",
        "testsrc2=size=160x90:rate=10",
        "-t",
        "0.5",
        "-c:v",
        "mpeg4",
        "-pix_fmt",
        "yuv420p",
        str(path),
    ]
    completed = subprocess.run(cmd, capture_output=True)
    if completed.returncode != 0:
        pytest.skip(f"ffmpeg cannot synthesise a clip: {completed.stderr[-200:]!r}")
    return path


def test_probe_real_clip(tiny_clip: Path) -> None:
    info = probe_media(tiny_clip)
    assert (info.width, info.height) == (160, 90)
    assert info.fps == pytest.approx(10.0, abs=0.5)
    assert info.duration == pytest.approx(0.5, abs=0.2)
    assert info.has_audio is False


def test_ffmpeg_source_scales_and_counts_frames(tiny_clip: Path) -> None:
    renderer = get_renderer("hd", width=32, rows=10)
    info = probe_media(tiny_clip)
    source = FFmpegSource(tiny_clip, renderer, info, fps=10)
    frames = list(source.frames())
    source.close()

    expected_width, expected_height = renderer.fit(info.width, info.height)
    assert len(frames) == 5
    for frame, _ in frames:
        assert frame.shape == (expected_height, expected_width, 3)
        assert frame.dtype.name == "uint8"
    assert [round(ts, 3) for _, ts in frames] == [0.0, 0.1, 0.2, 0.3, 0.4]


def test_missing_file_is_reported(tmp_path: Path) -> None:
    with pytest.raises(MediaError, match="file not found"):
        from curlcast.player import play

        play(tmp_path / "nope.mp4", get_renderer("hd", width=20))
