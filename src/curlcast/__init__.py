"""CurlCast — render photos, GIFs, and videos in crisp terminal art.

Public API surface
------------------
``curlcast.cli``
    Typer command line interface (``view``, ``play``, ``demo``).
``curlcast.player``
    Frame sources and the drift-corrected playback loop.
``curlcast.audio``
    Cross-platform audio backends with an audio-master playback clock.
``curlcast.renderers``
    Pluggable renderer strategy (``BaseRenderer`` → HD blocks / ASCII).
"""

from __future__ import annotations

__version__ = "0.1.0"
__author__ = "CurlCast Contributors"

__all__ = ["__version__", "__author__"]
