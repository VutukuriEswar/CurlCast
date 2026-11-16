"""Terminal capabilities and flicker-free frame output.

Everything that touches ANSI escape sequences lives here so the renderers stay
pure (image in, string out) and the player stays concerned with timing.

Windows notes
-------------
Legacy ``conhost`` needs two things before truecolor block art works:

* the output code page must be UTF-8 (``SetConsoleOutputCP(65001)``) or ``▀``
  raises ``UnicodeEncodeError`` / renders as mojibake;
* virtual terminal processing must be enabled (``ENABLE_VIRTUAL_TERMINAL_PROCESSING``)
  or escape sequences are printed literally.

Both are enabled best-effort in :func:`configure_streams`.
"""

from __future__ import annotations

import contextlib
import os
import shutil
import sys
from dataclasses import dataclass
from types import TracebackType
from typing import TextIO

HIDE_CURSOR = "\x1b[?25l"
SHOW_CURSOR = "\x1b[?25h"
CURSOR_HOME = "\x1b[H"
CLEAR_SCREEN = "\x1b[2J"
ERASE_BELOW = "\x1b[J"
RESET = "\x1b[0m"

_ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
_STD_OUTPUT_HANDLE = -11
_CP_UTF8 = 65001


@dataclass(frozen=True)
class TerminalSize:
    """Current terminal geometry in character cells."""

    columns: int
    rows: int


def get_size(fallback: tuple[int, int] = (80, 24)) -> TerminalSize:
    """Return the terminal size, clamped to something usable.

    ``shutil.get_terminal_size`` already consults ``COLUMNS``/``LINES`` and
    falls back to 80x24 when stdout is not a TTY (CI, pipes).
    """
    columns, rows = shutil.get_terminal_size(fallback=fallback)
    return TerminalSize(columns=max(columns, 10), rows=max(rows, 5))


def _enable_windows_ansi() -> None:
    if os.name != "nt":
        return
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        kernel32.SetConsoleOutputCP(_CP_UTF8)
        handle = kernel32.GetStdHandle(_STD_OUTPUT_HANDLE)
        mode = ctypes.c_uint32()
        if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            kernel32.SetConsoleMode(
                handle, mode.value | _ENABLE_VIRTUAL_TERMINAL_PROCESSING
            )
    except Exception:  # pragma: no cover - best effort on exotic consoles
        pass


def configure_streams() -> None:
    """Make stdout/stderr safe for truecolor block art.

    Idempotent; safe to call from ``main()`` on every invocation.
    """
    _enable_windows_ansi()
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        with contextlib.suppress(OSError, ValueError):  # redirected / closed
            reconfigure(encoding="utf-8", errors="replace")


def is_tty(stream: TextIO | None = None) -> bool:
    target = stream if stream is not None else sys.stdout
    try:
        return bool(target.isatty())
    except (AttributeError, ValueError):
        return False


class Screen:
    """Cursor-hiding frame writer that never clears the whole screen.

    A full ``ESC[2J`` between frames is what makes naive terminal video
    flicker. Instead we home the cursor (``ESC[H``), paint the frame and erase
    anything left below it (``ESC[J``). Output is a single write + flush per
    frame, so the terminal never sees a half-painted state.
    """

    def __init__(self, stream: TextIO | None = None, *, clear_on_enter: bool = True) -> None:
        self._stream = stream
        self._clear_on_enter = clear_on_enter
        self._closed = False

    @property
    def stream(self) -> TextIO:
        return self._stream if self._stream is not None else sys.stdout

    def __enter__(self) -> Screen:
        opening = HIDE_CURSOR
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

    def draw(self, frame: str) -> None:
        """Paint one complete frame in place."""
        self.write(CURSOR_HOME + frame + ERASE_BELOW)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        with contextlib.suppress(BrokenPipeError, ValueError):
            # stdout may have been closed (e.g. piped into `head`).
            self.write(RESET + SHOW_CURSOR + "\n")
