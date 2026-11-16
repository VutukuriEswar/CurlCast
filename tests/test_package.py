"""Packaging invariants: version single-sourcing and PEP 561 marker."""

from __future__ import annotations

import importlib.metadata
from pathlib import Path

import pytest

import curlcast


def test_py_typed_marker_ships_with_the_package() -> None:
    package_dir = Path(curlcast.__file__).parent
    assert (package_dir / "py.typed").is_file()


def test_installed_metadata_matches_runtime_version() -> None:
    try:
        installed = importlib.metadata.version("curlcast")
    except importlib.metadata.PackageNotFoundError:  # pragma: no cover - sdist run
        pytest.skip("curlcast is not installed in this environment")
    assert installed == curlcast.__version__


def test_public_api_is_importable() -> None:
    from curlcast import audio, cli, demo, ffmpeg, player, renderers, terminal

    assert callable(cli.main)
    assert renderers.available_modes() == ["ascii", "hd"]
    assert hasattr(audio, "AudioManager")
    assert hasattr(player, "play")
    assert hasattr(demo, "run_demo")
    assert hasattr(ffmpeg, "probe_media")
    assert hasattr(terminal, "Screen")
