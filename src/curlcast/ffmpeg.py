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

@dataclass(frozen=True)
class MediaInfo:
    width: int
    height: int
    fps: float
    duration: float | None
    has_audio: bool


@lru_cache(maxsize=1)
def ffmpeg_exe() -> str:
    try:
        import imageio_ffmpeg

        return str(imageio_ffmpeg.get_ffmpeg_exe())
    except Exception:
        return "ffmpeg"


def parse_probe(stderr: str) -> MediaInfo:
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
    cmd = [ffmpeg_exe(), "-hide_banner", "-nostdin", "-i", str(path)]
    try:
        completed = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=30,
        )
    except FileNotFoundError as exc:
        raise MediaError(
            "ffmpeg binary not found. Reinstall curlcast to restore the bundled build."
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise MediaError(f"ffmpeg timed out while probing {path.name}") from exc

    info = parse_probe(completed.stderr or "")
    if info.width <= 0 or info.height <= 0:
        raise MediaError(f"no video stream found in {path.name}")
    return info
