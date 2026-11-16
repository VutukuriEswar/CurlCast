from __future__ import annotations

import contextlib
import os
import platform
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

from curlcast.ffmpeg import ffmpeg_exe

SAMPLE_RATE = 48_000
CHANNELS = 2
BYTES_PER_SAMPLE = 2
CHUNK_FRAMES = 1024
CHUNK_BYTES = CHUNK_FRAMES * CHANNELS * BYTES_PER_SAMPLE

_SD_STATE: bool | None = None
_WARNED = False

def _sounddevice_available() -> bool:
    global _SD_STATE
    if _SD_STATE is None:
        try:
            __import__("sounddevice")
            _SD_STATE = True
        except Exception:
            _SD_STATE = False
    return _SD_STATE


def _subprocess_candidates() -> list[str]:
    names: list[str] = []
    if shutil.which("ffplay"):
        names.append("ffplay")
    if shutil.which("mpv"):
        names.append("mpv")
    if platform.system() == "Darwin" and shutil.which("afplay"):
        names.append("afplay")
    return names


def available_backends() -> list[str]:
    names: list[str] = []
    if _sounddevice_available():
        names.append("sounddevice")
    names.extend(_subprocess_candidates())
    return names


def _warn_silent() -> None:
    global _WARNED
    if _WARNED:
        return
    _WARNED = True
    from rich.console import Console

    Console(stderr=True).print(
        "[yellow]audio unavailable[/] — playing silently. "
        "Install [bold]ffplay[/] or [bold]mpv[/] to enable sound."
    )


def _terminate(proc: subprocess.Popen[Any]) -> None:
    if proc.poll() is not None:
        return
    try:
        proc.terminate()
        proc.wait(timeout=1.0)
    except Exception:
        with contextlib.suppress(Exception):
            proc.kill()


def _spawn(cmd: list[str]) -> subprocess.Popen[Any] | None:
    try:
        return subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except (FileNotFoundError, OSError):
        return None

class AudioManager:
    def __init__(self, source: Path, *, muted: bool = False, has_audio: bool = True) -> None:
        self._source = Path(source)
        self._muted = muted or not has_audio
        self._backend = "none"
        self._stream: Any = None
        self._stream_base = 0.0
        self._proc: subprocess.Popen[Any] | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._started_at: float | None = None
        self._temp_path: Path | None = None
        self._prepared = False
        self._seek = 0.0
        self._fallbacks: list[str] = []

    @property
    def backend(self) -> str:
        return self._backend

    @property
    def muted(self) -> bool:
        return self._muted

    def prepare(self, seek: float = 0.0) -> None:
        self.stop()
        self._stop.clear()
        self._seek = max(float(seek), 0.0)
        self._prepared = True

        if self._muted:
            self._backend = "muted"
            return

        if _sounddevice_available() and self._open_sounddevice():
            self._backend = "sounddevice"
            return

        self._backend = "none"
        self._fallbacks = _subprocess_candidates()

    def start(self, seek: float | None = None) -> None:
        if not self._prepared:
            self.prepare(seek if seek is not None else 0.0)
        elif seek is not None:
            self._seek = max(float(seek), 0.0)

        if self._backend == "sounddevice":
            if self._begin_sounddevice():
                return
            self._backend = "none"
            self._fallbacks = _subprocess_candidates()

        if self._backend == "muted":
            self._started_at = time.perf_counter()
            return

        if self._backend == "none":
            if self._fallbacks:
                self._backend = self._fallbacks.pop(0)
            else:
                self._started_at = time.perf_counter()
                self._warn_once_if_needed()
                return

        while self._backend != "none":
            backend = self._backend
            self._backend = "none"
            if self._start_subprocess(backend):
                return
            if not self._fallbacks:
                break
            self._backend = self._fallbacks.pop(0)

        self._started_at = time.perf_counter()
        self._warn_once_if_needed()

    def position(self) -> float:
        if self._backend == "sounddevice" and self._stream is not None:
            try:
                elapsed = float(self._stream.time) - self._stream_base
                return max(0.0, elapsed - float(self._stream.latency))
            except Exception:
                pass
        if self._started_at is None:
            return 0.0
        return max(0.0, time.perf_counter() - self._started_at)

    def stop(self) -> None:
        self._stop.set()

        stream, self._stream = self._stream, None
        if stream is not None:
            try:
                stream.abort(ignore_errors=True)
                stream.close(ignore_errors=True)
            except Exception:
                pass

        proc, self._proc = self._proc, None
        if proc is not None:
            _terminate(proc)

        thread, self._thread = self._thread, None
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=1.5)

        temp_path, self._temp_path = self._temp_path, None
        if temp_path is not None:
            with contextlib.suppress(OSError):
                temp_path.unlink(missing_ok=True)

        self._started_at = None
        self._stream_base = 0.0
        self._prepared = False
        self._fallbacks = []

    def _open_sounddevice(self) -> bool:
        try:
            import sounddevice as sd
        except Exception:
            return False

        cmd = [
            ffmpeg_exe(),
            "-hide_banner",
            "-loglevel",
            "error",
            "-nostdin",
            "-ss",
            f"{self._seek:.3f}",
            "-i",
            str(self._source),
            "-vn",
            "-sn",
            "-dn",
            "-f",
            "s16le",
            "-acodec",
            "pcm_s16le",
            "-ar",
            str(SAMPLE_RATE),
            "-ac",
            str(CHANNELS),
            "-",
        ]
        try:
            proc = subprocess.Popen(
                cmd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )
        except (FileNotFoundError, OSError):
            return False
        assert proc.stdout is not None

        stream = None
        for latency in ("low", None):
            try:
                stream = sd.RawOutputStream(
                    samplerate=SAMPLE_RATE,
                    channels=CHANNELS,
                    dtype="int16",
                    blocksize=CHUNK_FRAMES,
                    latency=latency,
                )
                break
            except Exception:
                stream = None
        if stream is None:
            _terminate(proc)
            return False

        self._proc = proc
        self._stream = stream
        return True

    def _begin_sounddevice(self) -> bool:
        proc, stream = self._proc, self._stream
        if proc is None or stream is None:
            return False
        try:
            stream.start()
            self._stream_base = float(stream.time)
        except Exception:
            proc, self._proc = self._proc, None
            if proc is not None:
                _terminate(proc)
            with contextlib.suppress(Exception):
                stream.close(ignore_errors=True)
            self._stream = None
            return False

        stop = self._stop
        frame_bytes = CHANNELS * BYTES_PER_SAMPLE

        def feed() -> None:
            stdout = proc.stdout
            assert stdout is not None
            try:
                while not stop.is_set():
                    chunk = stdout.read(CHUNK_BYTES)
                    if not chunk:
                        break
                    if len(chunk) % frame_bytes:
                        break
                    stream.write(chunk)
            except Exception:
                pass

        self._thread = threading.Thread(target=feed, name="curlcast-audio", daemon=True)
        self._thread.start()
        self._started_at = time.perf_counter()
        return True

    def _start_subprocess(self, backend: str) -> bool:
        started = self._start_afplay() if backend == "afplay" else self._start_player(backend)
        if started:
            self._backend = backend
            self._started_at = time.perf_counter()
        return started

    def _start_player(self, backend: str) -> bool:
        if backend == "ffplay":
            cmd = [
                "ffplay",
                "-nodisp",
                "-autoexit",
                "-loglevel",
                "error",
                "-ss",
                f"{self._seek:.3f}",
                "-i",
                str(self._source),
            ]
        else:
            cmd = [
                "mpv",
                "--no-video",
                "--really-quiet",
                "--no-terminal",
                f"--start={self._seek:.3f}",
                str(self._source),
            ]
        proc = _spawn(cmd)
        if proc is None:
            return False
        time.sleep(0.05)
        if proc.poll() is not None:
            return False
        self._proc = proc
        return True

    def _start_afplay(self) -> bool:
        handle, name = tempfile.mkstemp(prefix="curlcast-", suffix=".m4a")
        os.close(handle)
        temp_path = Path(name)
        cmd = [
            ffmpeg_exe(),
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-nostdin",
            "-i",
            str(self._source),
            "-vn",
            "-ac",
            "2",
            "-ar",
            "44100",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            str(temp_path),
        ]
        try:
            completed = subprocess.run(
                cmd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
        except OSError:
            temp_path.unlink(missing_ok=True)
            return False
        if completed.returncode != 0 or not temp_path.exists():
            temp_path.unlink(missing_ok=True)
            return False

        proc = _spawn(["afplay", str(temp_path)])
        if proc is None:
            temp_path.unlink(missing_ok=True)
            return False
        self._temp_path = temp_path
        self._proc = proc
        return True

    def _warn_once_if_needed(self) -> None:
        if not self._muted:
            _warn_silent()
