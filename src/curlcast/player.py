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
from curlcast.lyrics import LyricEngine
from curlcast.renderers.base import BaseRenderer
from curlcast.renderers.normal import Flashlight
from curlcast.server import StreamServer
from curlcast.terminal import Screen, get_size, poll_input

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

Frame = tuple[np.ndarray, float]


class FrameSource(Protocol):
    fps: float

    def frames(self) -> Iterator[Frame]:
        ...

    def close(self) -> None:
        ...


class Clock(Protocol):

    def position(self) -> float:
        ...


class PerfClock:

    def __init__(self) -> None:
        self._start = time.perf_counter()

    def position(self) -> float:
        return time.perf_counter() - self._start


def available_audio_backends() -> list[str]:
    from curlcast.audio import available_backends
    return available_backends()


def _read_exact(stream: IO[bytes], size: int) -> bytes | None:
    buffer = bytearray()
    try:
        while len(buffer) < size:
            chunk = stream.read(size - len(buffer))
            if not chunk:
                return None
            buffer.extend(chunk)
        return bytes(buffer)
    except (ValueError, OSError, BrokenPipeError):
        return None


class FFmpegSource:

    def __init__(
        self,
        path: Path,
        renderer: BaseRenderer,
        info: MediaInfo,
        fps: float,
        *,
        max_queue: int = 16,
    ) -> None:
        width = info.width
        height = info.height
        source_fps = info.fps or fps
        self._path = Path(path)
        self.source_size = (int(width), int(height))
        self._width, self._height = renderer.fit(int(width), int(height))
        self.fps = max(0.5, min(float(fps), float(source_fps)))
        self._max_queue = max(1, max_queue)
        self._proc: subprocess.Popen[bytes] | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

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
            except (ValueError, OSError, BrokenPipeError):
                pass
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

    def close(self) -> None:
        self._stop.set()
        proc, self._proc = self._proc, None
        thread, self._thread = self._thread, None
        if proc is not None:
            with contextlib.suppress(OSError):
                proc.kill()
            stdout = proc.stdout
            if stdout is not None:
                with contextlib.suppress(OSError, ValueError):
                    stdout.close()
            with contextlib.suppress(Exception):
                proc.wait(timeout=0.2)
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=0.2)


def _put(
    bucket: queue.Queue[np.ndarray | None],
    item: np.ndarray | None,
    stop: threading.Event,
) -> None:

    while not stop.is_set():
        try:
            bucket.put(item, timeout=0.05)
            return
        except queue.Full:
            continue


class GifSource:
    fps: float = 20.0

    def __init__(self, path: Path, renderer: BaseRenderer) -> None:
        self._path = Path(path)
        self._renderer = renderer
        self.source_size: tuple[int, int] | None = None
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
                if self.source_size is None:
                    self.source_size = frame.size
                if self._target is None:
                    self._target = self._renderer.fit(*frame.size)
                if frame.size != self._target:
                    frame = frame.resize(self._target, Image.Resampling.LANCZOS)

                yield np.asarray(frame, dtype=np.uint8), timestamp
                timestamp += delay
                index += 1
        finally:
            image.close()

    def close(self) -> None:
        pass


def render_loop(
    frames: Iterable[Frame],
    renderer: BaseRenderer,
    screen: Screen,
    clock: Clock,
    fps: float,
    *,
    source_size: tuple[int, int] | None = None,
    audio: AudioManager | None = None,
    lyrics: LyricEngine | None = None,
    flashlight: Flashlight | None = None,
    server: StreamServer | None = None,
    live: bool = False,
) -> None:

    last_size = (0, 0)
    for frame, timestamp in frames:
        if not live and (timestamp - clock.position() < -0.30):
            continue
        key = poll_input(0.0)
        if key == "EXIT":
            break
        elif flashlight is not None and key is not None:
            if key == "UP":
                flashlight.move(0.0, -0.06)
            elif key == "DOWN":
                flashlight.move(0.0, 0.06)
            elif key == "LEFT":
                flashlight.move(-0.06, 0.0)
            elif key == "RIGHT":
                flashlight.move(0.06, 0.0)

        if flashlight is not None:
            flashlight.update_time(timestamp)
            frame = flashlight.apply_light(frame)

        term = get_size()
        curr_size = (term.columns, term.rows)
        if curr_size != last_size:
            last_size = curr_size
            if hasattr(renderer, "refresh_size"):
                renderer.refresh_size()

        effective_source = (
            source_size if source_size is not None else (frame.shape[1], frame.shape[0])
        )
        fit_fn = getattr(renderer, "fit", None)
        if fit_fn is not None:
            target_w, target_h = fit_fn(effective_source[0], effective_source[1], upscale=False)
            if (frame.shape[1], frame.shape[0]) != (target_w, target_h):
                pil_frame = Image.fromarray(frame).resize(
                    (target_w, target_h), Image.Resampling.BILINEAR
                )
                frame = np.asarray(pil_frame)

        if lyrics is not None:
            curr_lyric = lyrics.get_line(timestamp)
            if curr_lyric and hasattr(renderer, "set_active_text"):
                renderer.set_active_text(curr_lyric)

        text = renderer.render(frame)

        if not live:
            wait = timestamp - clock.position()
            if wait > 0.002:
                time.sleep(wait - 0.0015)
            while timestamp - clock.position() > 0:
                pass

        if server is not None:
            server.broadcast_frame(text)
        screen.draw(text)


def _play_once(
    source: FrameSource,
    renderer: BaseRenderer,
    screen: Screen,
    audio: AudioManager,
    *,
    lyrics: LyricEngine | None = None,
    flashlight: Flashlight | None = None,
    server: StreamServer | None = None,
) -> None:

    audio.prepare()
    frames = source.frames()
    try:
        first = next(frames)
    except StopIteration:
        return

    audio.start()
    try:
        source_size = getattr(source, "source_size", None)
        render_loop(
            chain((first,), frames),
            renderer,
            screen,
            audio,
            source.fps,
            source_size=source_size,
            audio=audio,
            lyrics=lyrics,
            flashlight=flashlight,
            server=server,
        )
    finally:
        source.close()
        audio.stop()


def play(
    path: Path,
    renderer: BaseRenderer,
    fps: float = 20.0,
    loop: bool = False,
    muted: bool = False,
    lyrics: LyricEngine | None = None,
    flashlight: Flashlight | None = None,
    server: StreamServer | None = None,
    serve: int = 0,
) -> None:

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

    srv = server
    if srv is None and serve > 0:
        srv = StreamServer(port=serve)
        srv.start()

    try:
        screen = Screen()
        with screen:
            while True:
                renderer.refresh_size()
                _play_once(
                    make_source(),
                    renderer,
                    screen,
                    audio,
                    lyrics=lyrics,
                    flashlight=flashlight,
                    server=srv,
                )
                if not loop:
                    break
                time.sleep(0.15)
    finally:
        if srv is not None and srv is not server:
            srv.stop()
        audio.stop()
