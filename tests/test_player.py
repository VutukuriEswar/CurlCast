from __future__ import annotations

import io
import time

import numpy as np

from curlcast.audio import AudioManager, available_backends
from curlcast.player import PerfClock, render_loop
from curlcast.terminal import Screen


class FixedClock:
    def __init__(self, value: float) -> None:
        self.value = value

    def position(self) -> float:
        return self.value


class DummyRenderer:
    cols = 80
    rows = 24

    def render(self, frame: np.ndarray) -> str:
        return "FRAME"


class RecordingScreen:
    def __init__(self) -> None:
        self.frames: list[str] = []

    def write(self, text: str) -> None:
        pass

    def draw(self, frame: str) -> None:
        self.frames.append(frame)


def test_render_loop_drops_frames_that_are_more_than_two_late() -> None:
    frames = [
        (np.zeros((1, 1, 3), dtype=np.uint8), 1.0),
        (np.zeros((1, 1, 3), dtype=np.uint8), 9.9),
        (np.zeros((1, 1, 3), dtype=np.uint8), 10.0),
    ]
    screen = RecordingScreen()
    render_loop(iter(frames), DummyRenderer(), screen, FixedClock(10.0), fps=10)
    assert screen.frames == ["FRAME", "FRAME"]


def test_perf_clock_advances() -> None:
    clock = PerfClock()
    first = clock.position()
    time.sleep(0.02)
    assert clock.position() > first


def test_muted_audio_manager_acts_as_a_clock(tmp_path) -> None:
    audio = AudioManager(tmp_path / "ignored.mp4", muted=True)
    audio.prepare()
    assert audio.backend == "muted"
    assert audio.position() == 0.0

    audio.start()
    time.sleep(0.05)
    assert audio.position() >= 0.03

    audio.stop()
    assert audio.position() == 0.0


def test_no_audio_track_implies_muted(tmp_path) -> None:
    audio = AudioManager(tmp_path / "ignored.mp4", has_audio=False)
    audio.prepare()
    assert audio.muted is True
    assert audio.backend == "muted"


def test_backend_discovery_returns_strings() -> None:
    backends = available_backends()
    assert isinstance(backends, list)
    assert all(isinstance(backend, str) for backend in backends)


def test_screen_restores_cursor_and_resets_colour() -> None:
    buffer = io.StringIO()
    screen = Screen(buffer)
    with screen:
        screen.draw("ART")
    text = buffer.getvalue()
    assert text.startswith("\x1b[?25l")
    assert text.endswith("\x1b[0m\x1b[?25h\n")
    assert "\x1b[HART\x1b[J" in text
    screen.close()
    assert buffer.getvalue().count("\x1b[?25h") == 1


def test_screen_clear_emits_clear_and_home() -> None:
    buffer = io.StringIO()
    screen = Screen(buffer)
    screen.clear()
    assert "\x1b[2J\x1b[H" in buffer.getvalue()


def test_render_loop_resizes_frame_when_dimensions_differ() -> None:
    class SizingRenderer:
        def __init__(self) -> None:
            self.rendered_shapes: list[tuple[int, int]] = []

        def fit(self, w: int, h: int, upscale: bool = False) -> tuple[int, int]:
            return (40, 20)

        def refresh_size(self, *args, **kwargs) -> bool:
            return False

        def render(self, frame: np.ndarray) -> str:
            self.rendered_shapes.append(frame.shape[:2])
            return "FRAME"

    renderer = SizingRenderer()
    screen = RecordingScreen()
    frames = [(np.zeros((50, 100, 3), dtype=np.uint8), 0.0)]
    render_loop(iter(frames), renderer, screen, FixedClock(0.0), fps=10, source_size=(100, 50))
    assert len(renderer.rendered_shapes) == 1
    assert renderer.rendered_shapes[0] == (20, 40)
