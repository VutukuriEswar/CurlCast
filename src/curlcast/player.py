"""Frame sources and the drift-corrected playback loop.

Pipeline
--------
``FFmpegSource`` decodes with the bundled ffmpeg at exactly the size the
renderer wants (scaling happens in ffmpeg, not Python), a decoder thread pushes
frames into a tiny bounded queue, and the render loop paints the newest frame
on time. If rendering falls behind, stale frames are dropped instead of
letting the video drift away from the audio.

GIF playback uses Pillow (correct frame disposal/compositing and per-frame
delays) and is paced by cumulative timestamps, never by ``sleep(delay)``.

Cleanup is layered: the generator closes the decoder, ``play`` closes the
source, and ``Screen`` restores the cursor in ``__exit__``. Ctrl+C therefore
leaves a usable terminal and silent speakers.
"""

from __future__ import annotations

import contextlib
import queue
import subprocess
import threading
import time
from collections.abc import Iterable, Iterator
from itertools import chain
from pathlib import Path
from typing import IO, Protocol

import numpy as np
from PIL import Image

from curlcast.audio import AudioManager
from curlcast.ffmpeg import MediaError, MediaInfo, ffmpeg_exe, probe_media
from curlcast.renderers.base import BaseRenderer
from curlcast.terminal import Screen

__all__ = [
    "FFmpegSource",
    "Frame",
    "FrameSource",
    "GifSource",
    "MediaError",
    "PerfClock",
    "available_audio_backends",
    "play",
    "probe_media",
    "render_loop",
]

#: One decoded RGB frame plus its media timestamp in seconds.
Frame = tuple[np.ndarray, float]


class FrameSource(Protocol):
    """Anything that can produce timestamped RGB frames."""

    fps: float

    def frames(self) -> Iterator[Frame]:
        """Yield ``(rgb_array, timestamp)`` pairs, starting at 0.0."""

    def close(self) -> None:
        """Release decoder resources. Must be idempotent."""


class Clock(Protocol):
    """A source of media time in seconds (``AudioManager`` or ``PerfClock``)."""

    def position(self) -> float:
        """Seconds elapsed since playback started."""


class PerfClock:
    """Wall-clock fallback for audio-less sources (the demo, silent GIFs)."""

    def __init__(self) -> None:
        self._start = time.perf_counter()

    def position(self) -> float:
        return time.perf_counter() - self._start


def available_audio_backends() -> list[str]:
    """Backends usable on this machine (re-exported for the CLI)."""
    from curlcast.audio import available_backends

    return available_backends()


# ---------------------------------------------------------------------------
# ffmpeg-backed video
# ---------------------------------------------------------------------------


def _read_exact(stream: IO[bytes], size: int) -> bytes | None:
    """Read exactly ``size`` bytes, or return ``None`` at end of stream."""
    buffer = bytearray()
    while len(buffer) < size:
        chunk = stream.read(size - len(buffer))
        if not chunk:
            return None
        buffer.extend(chunk)
    return bytes(buffer)


class FFmpegSource:
    """Video decoder that produces frames already scaled for the terminal."""

    def __init__(
        self,
        path: Path,
        renderer: BaseRenderer,
        info: MediaInfo,
        fps: float,
        *,
        max_queue: int = 3,
    ) -> None:
        width = info.width
        height = info.height
        source_fps = info.fps or fps
        self._path = Path(path)
        self._width, self._height = renderer.fit(int(width), int(height))
        self.fps = max(0.5, min(float(fps), float(source_fps)))
        self._max_queue = max(1, max_queue)
        self._proc: subprocess.Popen[bytes] | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    # ------------------------------------------------------------------
    def frames(self) -> Iterator[Frame]:
        width, height = self._width, self._height
        frame_bytes = width * height * 3
        filters = (
            f"fps={self.fps:.6g},"
            f"scale={width}:{height}:flags=lanczos,"
            "setsar=1"
        )
        cmd = [
            ffmpeg_exe(),
            "-hide_banner",
            "-loglevel",
            "error",
            "-nostdin",
            "-re",
            "-i",
            str(self._path),
            "-an",
            "-sn",
            "-dn",
            "-vf",
            filters,
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "-",
        ]
        self._stop = threading.Event()
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        self._proc = proc
        assert proc.stdout is not None
        stop = self._stop
        frames: queue.Queue[np.ndarray | None] = queue.Queue(maxsize=self._max_queue)

        def decode() -> None:
            stdout = proc.stdout
            assert stdout is not None
            try:
                while not stop.is_set():
                    raw = _read_exact(stdout, frame_bytes)
                    if raw is None:
                        break
                    frame = np.frombuffer(raw, dtype=np.uint8).reshape(height, width, 3)
                    _put(frames, frame, stop)
            finally:
                _put(frames, None, stop)

        thread = threading.Thread(target=decode, name="curlcast-decode", daemon=True)
        self._thread = thread
        thread.start()

        index = 0
        try:
            while True:
                item = frames.get()
                if item is None:
                    break
                yield item, index / self.fps
                index += 1
        finally:
            self.close()

    # ------------------------------------------------------------------
    def close(self) -> None:
        self._stop.set()
        proc, self._proc = self._proc, None
        if proc is not None:
            with contextlib.suppress(OSError):
                proc.kill()
            stdout = proc.stdout
            if stdout is not None:
                with contextlib.suppress(OSError):
                    stdout.close()
            with contextlib.suppress(Exception):
                proc.wait(timeout=1.0)
        thread, self._thread = self._thread, None
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=1.0)


def _put(
    bucket: queue.Queue[np.ndarray | None],
    item: np.ndarray | None,
    stop: threading.Event,
) -> None:
    """Block until there is room, so real-time playback never loses the tail.

    A bounded queue provides backpressure to the decoder. The consumer still
    drops *late* frames in :func:`render_loop`, which is what keeps a slow
    terminal from drifting away from the audio.
    """
    while not stop.is_set():
        try:
            bucket.put(item, timeout=0.05)
            return
        except queue.Full:
            continue


# ---------------------------------------------------------------------------
# GIF
# ---------------------------------------------------------------------------


class GifSource:
    """Pillow-based animated GIF/WebP source with per-frame delays."""

    #: GIF timing is variable; 20 fps is only a hint for the drop policy.
    fps: float = 20.0

    def __init__(self, path: Path, renderer: BaseRenderer) -> None:
        self._path = Path(path)
        self._renderer = renderer
        self._target: tuple[int, int] | None = None

    def frames(self) -> Iterator[Frame]:
        image = Image.open(self._path)
        try:
            index = 0
            timestamp = 0.0
            while True:
                try:
                    image.seek(index)
                except EOFError:
                    break
                delay = float(image.info.get("duration", 80) or 80) / 1000.0
                delay = min(max(delay, 0.02), 10.0)

                frame = image.convert("RGB")
                if self._target is None:
                    self._target = self._renderer.fit(*frame.size)
                if frame.size != self._target:
                    frame = frame.resize(self._target, Image.Resampling.LANCZOS)

                yield np.asarray(frame, dtype=np.uint8), timestamp
                timestamp += delay
                index += 1
        finally:
            image.close()

    def close(self) -> None:  # pragma: no cover - generator owns the handle
        pass


# ---------------------------------------------------------------------------
# Playback loop
# ---------------------------------------------------------------------------


def render_loop(
    frames: Iterable[Frame],
    renderer: BaseRenderer,
    screen: Screen,
    clock: Clock,
    fps: float,
) -> None:
    """Paint timestamped frames in real time, dropping stale ones."""
    interval = 1.0 / max(fps, 1e-6)
    for frame, timestamp in frames:
        # Behind by more than two frames: drop rather than fall further back.
        if timestamp - clock.position() < -2.0 * interval:
            continue
        text = renderer.render(frame)
        wait = timestamp - clock.position()
        if wait > 0:
            time.sleep(wait)
        screen.draw(text)


def _play_once(
    source: FrameSource,
    renderer: BaseRenderer,
    screen: Screen,
    audio: AudioManager,
) -> None:
    # Open the audio device first (WASAPI/PortAudio setup can take a moment),
    # then decode frame 1. Nothing is audible until start(), so the decoder
    # cannot run ahead while the device initialises.
    audio.prepare()
    frames = source.frames()
    try:
        first = next(frames)
    except StopIteration:
        return

    audio.start()
    try:
        render_loop(chain((first,), frames), renderer, screen, audio, source.fps)
    finally:
        source.close()
        audio.stop()


def play(
    path: Path,
    renderer: BaseRenderer,
    fps: float = 20.0,
    loop: bool = False,
    muted: bool = False,
) -> None:
    """Play a video or GIF in the terminal.

    Parameters
    ----------
    path:
        Source file (``.mp4``/``.mov``/``.webm``/``.mkv``/``.gif``...).
    renderer:
        Instantiated renderer; it owns the output geometry.
    fps:
        Upper bound on display frame rate. Sources slower than this keep their
        native rate instead of duplicating frames.
    loop:
        Restart from the beginning when the source ends.
    muted:
        Skip audio entirely.
    """
    path = Path(path)
    if not path.exists():
        raise MediaError(f"file not found: {path}")

    is_gif = path.suffix.lower() == ".gif"
    if is_gif:
        info = None
        has_audio = False
    else:
        info = probe_media(path)
        has_audio = info.has_audio

    audio = AudioManager(path, muted=muted, has_audio=has_audio)

    def make_source() -> FrameSource:
        if is_gif:
            return GifSource(path, renderer)
        assert info is not None
        return FFmpegSource(path, renderer, info, fps)

    try:
        screen = Screen()
        with screen:
            while True:
                _play_once(make_source(), renderer, screen, audio)
                if not loop:
                    break
                time.sleep(0.15)
    finally:
        audio.stop()
