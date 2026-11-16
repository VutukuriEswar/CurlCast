"""Locating ffmpeg and probing media metadata.

``imageio-ffmpeg`` ships a portable ffmpeg binary inside its wheel, so the
common case (no system ffmpeg installed) works after a plain ``pip install``.
If the package is missing for any reason we fall back to ``ffmpeg`` on PATH.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

_DURATION_RE = re.compile(r"Duration:\s*(\d+):(\d{2}):(\d{2}(?:\.\d+)?)")
_VIDEO_RE = re.compile(r"Stream #\d+:\d+.*?: Video: .*?(\d{2,5})x(\d{2,5})")
_AUDIO_RE = re.compile(r"Stream #\d+:\d+.*?: Audio:")
_FPS_RE = re.compile(r"(\d+(?:\.\d+)?)\s+fps")
_ROTATE_RE = re.compile(
    r"(?:rotate\s*:\s*|rotation of\s+)(-?\d+(?:\.\d+)?)"
)


class MediaError(RuntimeError):
    """Raised when a file cannot be decoded as video."""


@dataclass(frozen=True)
class MediaInfo:
    """Metadata needed to schedule playback."""

    width: int
    height: int
    fps: float
    duration: float | None
    has_audio: bool


@lru_cache(maxsize=1)
def ffmpeg_exe() -> str:
    """Absolute path to a usable ffmpeg binary."""
    try:
        import imageio_ffmpeg

        return str(imageio_ffmpeg.get_ffmpeg_exe())
    except Exception:  # pragma: no cover - imageio-ffmpeg is a hard dependency
        return "ffmpeg"


def parse_probe(stderr: str) -> MediaInfo:
    """Parse the stderr of ``ffmpeg -i <file>`` into :class:`MediaInfo`.

    Pure function so the parsing rules are unit-testable without ffmpeg.
    """
    video_line = ""
    for line in stderr.splitlines():
        if "Video:" in line:
            video_line = line
            break

    width = height = 0
    match = _VIDEO_RE.search(video_line)
    if match:
        width, height = int(match.group(1)), int(match.group(2))

    fps = 0.0
    fps_match = _FPS_RE.search(video_line)
    if fps_match:
        fps = float(fps_match.group(1))

    duration: float | None = None
    duration_match = _DURATION_RE.search(stderr)
    if duration_match:
        hours, minutes, seconds = duration_match.groups()
        duration = int(hours) * 3600 + int(minutes) * 60 + float(seconds)

    # ffmpeg autorotates before filters, so report the displayed geometry.
    rotation_match = _ROTATE_RE.search(stderr)
    if rotation_match:
        rotation = float(rotation_match.group(1))
        if round(abs(rotation)) % 180 == 90:
            width, height = height, width

    return MediaInfo(
        width=width,
        height=height,
        fps=fps,
        duration=duration,
        has_audio=bool(_AUDIO_RE.search(stderr)),
    )


def probe_media(path: Path) -> MediaInfo:
    """Run a fast ffmpeg header probe and parse the result."""
    cmd = [ffmpeg_exe(), "-hide_banner", "-nostdin", "-i", str(path)]
    try:
        completed = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=30,
        )
    except FileNotFoundError as exc:  # pragma: no cover - broken install
        raise MediaError(
            "ffmpeg binary not found. Reinstall curlcast to restore the bundled build."
        ) from exc
    except subprocess.TimeoutExpired as exc:  # pragma: no cover - pathological file
        raise MediaError(f"ffmpeg timed out while probing {path.name}") from exc

    info = parse_probe(completed.stderr or "")
    if info.width <= 0 or info.height <= 0:
        raise MediaError(f"no video stream found in {path.name}")
    return info
