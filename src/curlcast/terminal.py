from __future__ import annotations

import contextlib
import os
import shutil
import sys
import time
from dataclasses import dataclass
from types import TracebackType
from typing import Any, TextIO

HIDE_CURSOR = "\x1b[?25l"
SHOW_CURSOR = "\x1b[?25h"
CURSOR_HOME = "\x1b[H"
CLEAR_SCREEN = "\x1b[2J"
ERASE_BELOW = "\x1b[J"
RESET = "\x1b[0m"
DECAWM_DISABLE = "\x1b[?7l"
DECAWM_ENABLE = "\x1b[?7h"

_ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
_STD_OUTPUT_HANDLE = -11
_CP_UTF8 = 65001


@dataclass(frozen=True)
class TerminalSize:
    columns: int
    rows: int


def get_size(fallback: tuple[int, int] = (80, 24)) -> TerminalSize:
    columns, rows = shutil.get_terminal_size(fallback=fallback)
    return TerminalSize(columns=max(columns, 10), rows=max(rows, 5))


def _enable_windows_ansi() -> None:
    if os.name != "nt":
        return
    try:
        import ctypes

        windll: Any = getattr(ctypes, "windll", None)
        if windll is None:
            return
        kernel32 = windll.kernel32
        kernel32.SetConsoleOutputCP(_CP_UTF8)
        handle = kernel32.GetStdHandle(_STD_OUTPUT_HANDLE)
        mode = ctypes.c_uint32()
        if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            kernel32.SetConsoleMode(
                handle, mode.value | _ENABLE_VIRTUAL_TERMINAL_PROCESSING
            )
    except Exception:
        pass


def configure_streams() -> None:
    _enable_windows_ansi()
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        with contextlib.suppress(OSError, ValueError):
            reconfigure(encoding="utf-8", errors="replace")


def is_tty(stream: TextIO | None = None) -> bool:
    target = stream if stream is not None else sys.stdout
    try:
        return bool(target.isatty())
    except (AttributeError, ValueError):
        return False


class Screen:
    def __init__(self, stream: TextIO | None = None, *, clear_on_enter: bool = True) -> None:
        self._stream = stream
        self._clear_on_enter = clear_on_enter
        self._closed = False

    @property
    def stream(self) -> TextIO:
        return self._stream if self._stream is not None else sys.stdout

    def __enter__(self) -> Screen:
        if os.name == "nt":
            with contextlib.suppress(Exception):
                import ctypes

                windll: Any = getattr(ctypes, "windll", None)
                if windll is not None:
                    windll.winmm.timeBeginPeriod(1)
        opening = HIDE_CURSOR + DECAWM_DISABLE
        if self._clear_on_enter:
            opening += CLEAR_SCREEN
        self.write(opening + CURSOR_HOME)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def write(self, text: str) -> None:
        stream = self.stream
        stream.write(text)
        stream.flush()

    def clear(self) -> None:
        self.write(CLEAR_SCREEN + CURSOR_HOME)

    def draw(self, frame: str) -> None:
        body = "\x1b[K\n".join(frame.split("\n")) + "\x1b[K" if "\n" in frame else frame
        self.write(CURSOR_HOME + body + ERASE_BELOW)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if os.name == "nt":
            with contextlib.suppress(Exception):
                import ctypes

                windll: Any = getattr(ctypes, "windll", None)
                if windll is not None:
                    windll.winmm.timeEndPeriod(1)
        with contextlib.suppress(BrokenPipeError, ValueError):
            self.write(RESET + SHOW_CURSOR + DECAWM_ENABLE + "\n")


def poll_input(timeout: float = 0.0) -> str | None:
    try:
        if os.name == "nt":
            import msvcrt

            msvcrt_any: Any = msvcrt
            end_time = time.perf_counter() + max(0.0, timeout)
            while True:
                if msvcrt_any.kbhit():
                    ch = msvcrt_any.getch()
                    if ch in (b"\x00", b"\xe0"):
                        ch2 = msvcrt_any.getch()
                        if ch2 == b"H":
                            return "UP"
                        if ch2 == b"P":
                            return "DOWN"
                        if ch2 == b"K":
                            return "LEFT"
                        if ch2 == b"M":
                            return "RIGHT"
                    elif ch in (b"w", b"W"):
                        return "UP"
                    elif ch in (b"s", b"S"):
                        return "DOWN"
                    elif ch in (b"a", b"A"):
                        return "LEFT"
                    elif ch in (b"d", b"D"):
                        return "RIGHT"
                    elif ch in (b"q", b"Q", b"\x1b", b"\r", b"\n", b" ", b"\x03"):
                        return "EXIT"
                if time.perf_counter() >= end_time:
                    break
                time.sleep(0.005)
            return None
        else:
            import select

            r, _, _ = select.select([sys.stdin], [], [], max(0.0, timeout))
            if r:
                char_in = sys.stdin.read(1)
                if char_in in ("q", "Q", "\r", "\n", " ", "\x03"):
                    return "EXIT"
                if char_in in ("w", "W"):
                    return "UP"
                if char_in in ("s", "S"):
                    return "DOWN"
                if char_in in ("a", "A"):
                    return "LEFT"
                if char_in in ("d", "D"):
                    return "RIGHT"
                if char_in == "\x1b":
                    r2, _, _ = select.select([sys.stdin], [], [], 0.02)
                    if r2:
                        seq = sys.stdin.read(2)
                        if seq == "[A":
                            return "UP"
                        if seq == "[B":
                            return "DOWN"
                        if seq == "[C":
                            return "RIGHT"
                        if seq == "[D":
                            return "LEFT"
                    return "EXIT"
            return None
    except Exception:
        return None


def check_exit_key(timeout: float = 0.0) -> bool:
    return poll_input(timeout=timeout) == "EXIT"
