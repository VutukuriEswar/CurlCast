from __future__ import annotations

import socket
import time

import numpy as np
from typer.testing import CliRunner

from curlcast.capture import ScreenSource, WebcamSource
from curlcast.cli import app
from curlcast.renderers.ascii import AsciiRenderer
from curlcast.server import StreamServer


def test_stream_server_lifecycle():
    server = StreamServer(host="127.0.0.1", port=18899)
    assert server.client_count == 0
    server.start()

    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.connect(("127.0.0.1", 18899))
    s.sendall(b"GET / HTTP/1.1\r\nHost: localhost\r\n\r\n")

    time.sleep(0.1)
    assert server.client_count == 1

    server.broadcast_frame("CURLCAST_TEST_FRAME")
    time.sleep(0.1)

    data = s.recv(4096)
    assert b"HTTP/1.1 200 OK" in data
    assert b"CURLCAST_TEST_FRAME" in data

    s.close()
    time.sleep(0.1)
    server.stop()
    assert server.client_count == 0


def test_screen_source():
    renderer = AsciiRenderer(width=30, rows=15)
    source = ScreenSource(renderer, fps=20.0)
    it = source.frames()
    frame, ts = next(it)
    assert isinstance(frame, np.ndarray)
    assert frame.ndim == 3
    assert frame.shape[2] == 3
    assert ts >= 0.0
    source.close()


def test_screen_source_regions():
    renderer = AsciiRenderer(width=30, rows=15)
    for reg in ("top-left", "top-right", "bottom-left", "bottom-right", "10,10,60,40"):
        source = ScreenSource(renderer, fps=20.0, region=reg)
        it = source.frames()
        frame, ts = next(it)
        assert isinstance(frame, np.ndarray)
        assert frame.ndim == 3
        source.close()


def test_window_manager():
    from curlcast.capture import WindowManager
    wm = WindowManager(region="top-left")
    assert wm.region == "top-left"
    wm.setup()
    _ = wm.get_window_box()
    wm.restore()


def test_webcam_source_testsrc():
    renderer = AsciiRenderer(width=30, rows=15)
    source = WebcamSource(renderer, device="none", fps=15.0, width=160, height=120)
    it = source.frames()
    frame, ts = next(it)
    assert isinstance(frame, np.ndarray)
    assert frame.shape == (120, 160, 3)
    assert ts >= 0.0
    source.close()


def test_cli_phase4_commands_help():
    from conftest import strip_ansi

    runner = CliRunner()
    res_root = runner.invoke(app, ["--help"], env={"NO_COLOR": "1", "COLUMNS": "200"})
    assert res_root.exit_code == 0
    root_out = strip_ansi(res_root.output)
    assert "cam" in root_out
    assert "screen" in root_out
    assert "broadcast" in root_out

    res_cam = runner.invoke(app, ["cam", "--help"], env={"NO_COLOR": "1", "COLUMNS": "200"})
    assert res_cam.exit_code == 0
    cam_out = strip_ansi(res_cam.output)
    assert "--fps" in cam_out
    assert "--serve" in cam_out

    res_screen = runner.invoke(app, ["screen", "--help"], env={"NO_COLOR": "1", "COLUMNS": "200"})
    assert res_screen.exit_code == 0
    screen_out = strip_ansi(res_screen.output)
    assert "--fps" in screen_out

    res_bcast = runner.invoke(app, ["broadcast", "--help"], env={"NO_COLOR": "1", "COLUMNS": "200"})
    assert res_bcast.exit_code == 0
    bcast_out = strip_ansi(res_bcast.output)
    assert "--port" in bcast_out
