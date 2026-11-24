from __future__ import annotations

import contextlib
import os
import queue
import subprocess
import sys
import threading
import time
from collections.abc import Iterator
from typing import Any, cast

import numpy as np
from PIL import Image, ImageGrab

from curlcast.ffmpeg import ffmpeg_exe
from curlcast.renderers.base import BaseRenderer

Frame = tuple[np.ndarray, float]


def _resolve_bbox(region: str) -> tuple[int, int, int, int] | None:
    reg = region.strip().lower()
    if not reg:
        return None
    try:
        if "," in reg:
            parts = [int(p.strip()) for p in reg.split(",")]
            if len(parts) == 4:
                x, y, w, h = parts
                return (x, y, x + w, y + h)
        full_w, full_h = ImageGrab.grab().size
        if reg == "left":
            return (0, 0, full_w // 2, full_h)
        if reg == "right":
            return (full_w // 2, 0, full_w, full_h)
        if reg == "top":
            return (0, 0, full_w, full_h // 2)
        if reg == "bottom":
            return (0, full_h // 2, full_w, full_h)
    except Exception:
        return None
    return None


def _find_terminal_window() -> int:
    if os.name != "nt":
        return 0
    import ctypes
    from ctypes import wintypes

    windll: Any = getattr(ctypes, "windll", None)
    if windll is None:
        return 0
    user32 = windll.user32
    kernel32 = windll.kernel32

    def _get_class(h: int) -> str:
        buf = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(h, buf, 256)
        return buf.value

    fg = user32.GetForegroundWindow()
    if fg and user32.IsWindowVisible(fg):
        root = user32.GetAncestor(fg, 2) or fg
        cname = _get_class(root)
        if "CASCADIA" in cname or "Console" in cname or "Terminal" in cname:
            return int(root)

    found_cascadia: list[int] = []
    found_console: list[int] = []

    def enum_cb(h: int, _: int) -> bool:
        if user32.IsWindowVisible(h):
            cname = _get_class(h)
            if "CASCADIA" in cname:
                found_cascadia.append(h)
            elif "Console" in cname:
                found_console.append(h)
        return True

    winfunctype: Any = getattr(ctypes, "WINFUNCTYPE", ctypes.CFUNCTYPE)
    WNDENUMPROC = winfunctype(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows(WNDENUMPROC(enum_cb), 0)

    if found_cascadia:
        return int(found_cascadia[0])
    if fg and user32.IsWindowVisible(fg):
        return int(user32.GetAncestor(fg, 2) or fg)
    if found_console:
        return int(found_console[0])

    cw = kernel32.GetConsoleWindow()
    if cw and user32.IsWindowVisible(cw):
        return int(user32.GetAncestor(cw, 2) or cw)
    return 0


def _capture_clean_desktop() -> np.ndarray | None:
    if os.name != "nt":
        try:
            return np.array(ImageGrab.grab().convert("RGB"), copy=True)
        except Exception:
            return None
    import ctypes
    from ctypes import wintypes

    try:
        windll: Any = getattr(ctypes, "windll", None)
        if windll is None:
            return None
        user32 = windll.user32
        gdi32 = windll.gdi32
        h_dc = user32.GetDC(0)
        sw = gdi32.GetDeviceCaps(h_dc, 8)
        sh = gdi32.GetDeviceCaps(h_dc, 10)
        if sw <= 0:
            sw = user32.GetSystemMetrics(0)
        if sh <= 0:
            sh = user32.GetSystemMetrics(1)
        h_mem_dc = gdi32.CreateCompatibleDC(h_dc)

        class BITMAPINFOHEADER(ctypes.Structure):
            _fields_ = [
                ("biSize", wintypes.DWORD),
                ("biWidth", wintypes.LONG),
                ("biHeight", wintypes.LONG),
                ("biPlanes", wintypes.WORD),
                ("biBitCount", wintypes.WORD),
                ("biCompression", wintypes.DWORD),
                ("biSizeImage", wintypes.DWORD),
                ("biXPelsPerMeter", wintypes.LONG),
                ("biYPelsPerMeter", wintypes.LONG),
                ("biClrUsed", wintypes.DWORD),
                ("biClrImportant", wintypes.DWORD),
            ]

        bmi = BITMAPINFOHEADER()
        bmi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        bmi.biWidth = sw
        bmi.biHeight = -sh
        bmi.biPlanes = 1
        bmi.biBitCount = 32
        p_bits = ctypes.c_void_p()
        h_bmp = gdi32.CreateDIBSection(
            h_mem_dc, ctypes.byref(bmi), 0, ctypes.byref(p_bits), None, 0
        )
        gdi32.SelectObject(h_mem_dc, h_bmp)
        gdi32.BitBlt(h_mem_dc, 0, 0, sw, sh, h_dc, 0, 0, 0x00CC0020)
        arr = np.ctypeslib.as_array(
            ctypes.cast(p_bits, ctypes.POINTER(ctypes.c_uint8)),
            shape=(sh, sw, 4),
        )
        rgb = arr[:, :, [2, 1, 0]].copy()
        gdi32.DeleteObject(h_bmp)
        gdi32.DeleteDC(h_mem_dc)
        user32.ReleaseDC(0, h_dc)
        return cast("np.ndarray", rgb)
    except Exception:
        try:
            return np.array(ImageGrab.grab().convert("RGB"), copy=True)
        except Exception:
            return None


class FastScreenCapture:
    def __init__(self, target_w: int, target_h: int) -> None:
        self.tw = max(10, int(target_w))
        self.th = max(5, int(target_h))
        self._ok = False
        if os.name != "nt":
            return
        import ctypes
        from ctypes import wintypes

        try:
            windll: Any = getattr(ctypes, "windll", None)
            if windll is None:
                return
            self.user32 = windll.user32
            self.gdi32 = windll.gdi32

            self.hScreenDC = self.user32.GetDC(0)
            self.sw = self.gdi32.GetDeviceCaps(self.hScreenDC, 8)
            self.sh = self.gdi32.GetDeviceCaps(self.hScreenDC, 10)
            if self.sw <= 0:
                self.sw = self.user32.GetSystemMetrics(0)
            if self.sh <= 0:
                self.sh = self.user32.GetSystemMetrics(1)

            self.hMemoryDC = self.gdi32.CreateCompatibleDC(self.hScreenDC)

            class BITMAPINFOHEADER(ctypes.Structure):
                _fields_ = [
                    ("biSize", wintypes.DWORD),
                    ("biWidth", wintypes.LONG),
                    ("biHeight", wintypes.LONG),
                    ("biPlanes", wintypes.WORD),
                    ("biBitCount", wintypes.WORD),
                    ("biCompression", wintypes.DWORD),
                    ("biSizeImage", wintypes.DWORD),
                    ("biXPelsPerMeter", wintypes.LONG),
                    ("biYPelsPerMeter", wintypes.LONG),
                    ("biClrUsed", wintypes.DWORD),
                    ("biClrImportant", wintypes.DWORD),
                ]

            bmi = BITMAPINFOHEADER()
            bmi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
            bmi.biWidth = self.tw
            bmi.biHeight = -self.th
            bmi.biPlanes = 1
            bmi.biBitCount = 32
            bmi.biCompression = 0

            self.pBits = ctypes.c_void_p()
            self.hBitmap = self.gdi32.CreateDIBSection(
                self.hMemoryDC,
                ctypes.byref(bmi),
                0,
                ctypes.byref(self.pBits),
                None,
                0,
            )
            self.gdi32.SelectObject(self.hMemoryDC, self.hBitmap)
            self.gdi32.SetStretchBltMode(self.hMemoryDC, 4)
            self.gdi32.SetBrushOrgEx(self.hMemoryDC, 0, 0, None)

            self._arr = np.ctypeslib.as_array(
                ctypes.cast(self.pBits, ctypes.POINTER(ctypes.c_uint8)),
                shape=(self.th, self.tw, 4),
            )
            self._ok = True
        except Exception:
            self._ok = False

    def grab(self) -> np.ndarray | None:
        if not self._ok:
            return None
        try:
            self.gdi32.StretchBlt(
                self.hMemoryDC,
                0,
                0,
                self.tw,
                self.th,
                self.hScreenDC,
                0,
                0,
                self.sw,
                self.sh,
                0x00CC0020,
            )
            return cast("np.ndarray", self._arr[:, :, [2, 1, 0]].copy())
        except Exception:
            return None

    def close(self) -> None:
        if self._ok:
            with contextlib.suppress(Exception):
                self.gdi32.DeleteObject(self.hBitmap)
                self.gdi32.DeleteDC(self.hMemoryDC)
                self.user32.ReleaseDC(0, self.hScreenDC)
            self._ok = False


class WindowManager:
    def __init__(self, region: str = "") -> None:
        self.region = str(region).strip().lower()
        self.hwnd: int = 0
        self.orig_rect: tuple[int, int, int, int] | None = None
        self.was_maximized: bool = False

    def setup(self) -> np.ndarray | None:
        if os.name != "nt":
            return None
        import ctypes
        from ctypes import wintypes

        try:
            windll: Any = getattr(ctypes, "windll", None)
            if windll is None:
                return None
            try:
                windll.shcore.SetProcessDpiAwareness(2)
            except Exception:
                with contextlib.suppress(Exception):
                    windll.user32.SetProcessDPIAware()

            user32 = windll.user32
            hwnd = _find_terminal_window()
            if not hwnd:
                return None

            class POINT(ctypes.Structure):
                _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]

            class RECT(ctypes.Structure):
                _fields_ = [
                    ("left", wintypes.LONG),
                    ("top", wintypes.LONG),
                    ("right", wintypes.LONG),
                    ("bottom", wintypes.LONG),
                ]

            class WINDOWPLACEMENT(ctypes.Structure):
                _fields_ = [
                    ("length", wintypes.UINT),
                    ("flags", wintypes.UINT),
                    ("showCmd", wintypes.UINT),
                    ("ptMinPosition", POINT),
                    ("ptMaxPosition", POINT),
                    ("rcNormalPosition", RECT),
                ]

            rect = RECT()
            if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
                return None

            self.hwnd = hwnd
            self.orig_rect = (
                rect.left,
                rect.top,
                rect.right - rect.left,
                rect.bottom - rect.top,
            )
            self.was_maximized = bool(user32.IsZoomed(hwnd))

            self.orig_placement = WINDOWPLACEMENT()
            self.orig_placement.length = ctypes.sizeof(WINDOWPLACEMENT)
            user32.GetWindowPlacement(hwnd, ctypes.byref(self.orig_placement))

            screen_w = user32.GetSystemMetrics(0)
            screen_h = user32.GetSystemMetrics(1)
            scale = 1.0
            if hasattr(user32, "GetDpiForWindow"):
                dpi = user32.GetDpiForWindow(hwnd)
                if dpi:
                    scale = dpi / 96.0

            reg = self.region
            pad = int(24 * scale)
            taskbar_pad = int(60 * scale)

            if not reg or reg in ("center", "centre", "full", "max", "all"):
                win_w = max(int(1050 * scale), min(int(1450 * scale), int(screen_w * 0.72)))
                win_h = max(int(680 * scale), min(int(980 * scale), int(screen_h * 0.82)))
                x = max(pad, (screen_w - win_w) // 2)
                y = pad
            else:
                pip_w = max(int(660 * scale), min(int(960 * scale), int(screen_w * 0.44)))
                pip_h = max(int(440 * scale), min(int(680 * scale), int(screen_h * 0.46)))
                win_w = pip_w
                win_h = pip_h
                if reg in ("top-right", "tr", "right"):
                    x, y = screen_w - pip_w - pad, pad
                elif reg in ("bottom-left", "bl", "bottom"):
                    x, y = pad, screen_h - pip_h - taskbar_pad
                elif reg in ("bottom-right", "br"):
                    x, y = screen_w - pip_w - pad, screen_h - pip_h - taskbar_pad
                else:
                    x, y = pad, pad

            if self.was_maximized:
                user32.ShowWindow(hwnd, 9)
                time.sleep(0.04)

            user32.MoveWindow(hwnd, -30000, -30000, win_w, win_h, False)
            time.sleep(0.05)
            clean_shot = _capture_clean_desktop()

            user32.MoveWindow(hwnd, x, y, win_w, win_h, True)
            user32.ShowWindow(hwnd, 5)
            user32.SetWindowPos(
                hwnd,
                ctypes.c_void_p(-1),
                x,
                y,
                win_w,
                win_h,
                0x0040 | 0x0020,
            )
            return clean_shot
        except Exception:
            return None

    def get_window_box(self) -> tuple[int, int, int, int] | None:
        if not self.hwnd or os.name != "nt":
            return None
        import ctypes
        from ctypes import wintypes

        try:
            class RECT(ctypes.Structure):
                _fields_ = [
                    ("left", wintypes.LONG),
                    ("top", wintypes.LONG),
                    ("right", wintypes.LONG),
                    ("bottom", wintypes.LONG),
                ]

            rect = RECT()
            windll: Any = getattr(ctypes, "windll", None)
            if windll is None:
                return None
            user32 = windll.user32
            dwmapi = getattr(windll, "dwmapi", None)
            got_rect = False
            if dwmapi is not None:
                hr = dwmapi.DwmGetWindowAttribute(
                    self.hwnd, 9, ctypes.byref(rect), ctypes.sizeof(rect)
                )
                if hr == 0:
                    got_rect = True
            if not got_rect and not user32.GetWindowRect(self.hwnd, ctypes.byref(rect)):
                return None

            pad = 4
            return (
                rect.left - pad,
                rect.top - pad,
                rect.right + pad,
                rect.bottom + pad,
            )
        except Exception:
            return None

    def restore(self) -> None:
        if not self.hwnd or os.name != "nt":
            return
        import ctypes

        try:
            windll: Any = getattr(ctypes, "windll", None)
            if windll is None:
                return
            user32 = windll.user32
            with contextlib.suppress(Exception):
                user32.SetWindowDisplayAffinity(self.hwnd, 0)
            user32.SetWindowPos(
                self.hwnd,
                ctypes.c_void_p(-2),
                0,
                0,
                0,
                0,
                0x0001 | 0x0002 | 0x0020,
            )
            if self.was_maximized:
                user32.ShowWindow(self.hwnd, 3)
            elif hasattr(self, "orig_placement"):
                user32.SetWindowPlacement(self.hwnd, ctypes.byref(self.orig_placement))
                if self.orig_rect:
                    user32.MoveWindow(
                        self.hwnd,
                        self.orig_rect[0],
                        self.orig_rect[1],
                        self.orig_rect[2],
                        self.orig_rect[3],
                        True,
                    )
            elif self.orig_rect:
                user32.MoveWindow(
                    self.hwnd,
                    self.orig_rect[0],
                    self.orig_rect[1],
                    self.orig_rect[2],
                    self.orig_rect[3],
                    True,
                )
        except Exception:
            pass


class ScreenSource:
    def __init__(
        self,
        renderer: BaseRenderer,
        fps: float = 30.0,
        region: str = "",
        window_mgr: WindowManager | None = None,
        initial_bg: np.ndarray | None = None,
    ) -> None:
        self._renderer = renderer
        self.fps = max(1.0, float(fps))
        self.region = str(region).strip().lower()
        self._win_mgr = window_mgr
        self._bbox = None
        if "," in self.region:
            self._bbox = _resolve_bbox(self.region)

        self._fast_cap: FastScreenCapture | None = None
        if os.name == "nt" and self._bbox is None:
            fit_fn = getattr(renderer, "fit", None)
            tw, th = fit_fn(1600, 1000, upscale=False) if fit_fn is not None else (120, 40)
            self._fast_cap = FastScreenCapture(tw, th)

        if self._fast_cap is not None:
            self.source_size: tuple[int, int] | None = (self._fast_cap.sw, self._fast_cap.sh)
        elif self._bbox is not None:
            self.source_size = (
                self._bbox[2] - self._bbox[0],
                self._bbox[3] - self._bbox[1],
            )
        else:
            try:
                self.source_size = ImageGrab.grab().size
            except Exception:
                self.source_size = (1920, 1080)

        fit_fn = getattr(renderer, "fit", None)
        if fit_fn is not None and self.source_size is not None:
            self._target_size = fit_fn(self.source_size[0], self.source_size[1], upscale=False)
        else:
            self._target_size = (120, 40)

        if (
            self._fast_cap is not None
            and (self._fast_cap.tw, self._fast_cap.th) != self._target_size
        ):
            self._fast_cap.close()
            self._fast_cap = FastScreenCapture(self._target_size[0], self._target_size[1])

        self._bg_buffer: np.ndarray | None = None
        if initial_bg is not None:
            try:
                pil_bg = Image.fromarray(initial_bg).resize(
                    (self._target_size[0], self._target_size[1]), Image.Resampling.BILINEAR
                )
                self._bg_buffer = np.array(pil_bg, copy=True)
            except Exception:
                self._bg_buffer = None

        self._stop = threading.Event()

    def frames(self) -> Iterator[Frame]:
        index = 0
        interval = 1.0 / self.fps
        target_time = time.perf_counter()

        while not self._stop.is_set():
            arr: np.ndarray | None = None
            if self._fast_cap is not None:
                arr = self._fast_cap.grab()

            if arr is None:
                try:
                    grabbed = ImageGrab.grab(bbox=self._bbox) if self._bbox else ImageGrab.grab()
                except Exception:
                    grabbed = Image.new("RGB", (640, 480), (30, 30, 40))
                arr = np.array(grabbed.convert("RGB"), copy=True)

            if self._win_mgr is not None and self._win_mgr.hwnd and arr is not None:
                box = self._win_mgr.get_window_box()
                if box is not None:
                    th, tw = arr.shape[:2]
                    default_sw = self.source_size[0] if self.source_size else 1600
                    default_sh = self.source_size[1] if self.source_size else 1000
                    sw = getattr(self._fast_cap, "sw", default_sw)
                    sh = getattr(self._fast_cap, "sh", default_sh)
                    bx1 = max(0, min(tw, int(round(box[0] * tw / sw))))
                    by1 = max(0, min(th, int(round(box[1] * th / sh))))
                    bx2 = max(0, min(tw, int(round(box[2] * tw / sw))))
                    by2 = max(0, min(th, int(round(box[3] * th / sh))))

                    if bx2 > bx1 and by2 > by1:
                        if self._bg_buffer is None or self._bg_buffer.shape[:2] != (th, tw):
                            self._bg_buffer = arr.copy()
                        else:
                            if not self._bg_buffer.flags.writeable:
                                self._bg_buffer = self._bg_buffer.copy()
                            if by1 > 0:
                                self._bg_buffer[:by1, :] = arr[:by1, :]
                            if by2 < th:
                                self._bg_buffer[by2:, :] = arr[by2:, :]
                            if bx1 > 0:
                                self._bg_buffer[by1:by2, :bx1] = arr[by1:by2, :bx1]
                            if bx2 < tw:
                                self._bg_buffer[by1:by2, bx2:] = arr[by1:by2, bx2:]

                        if not arr.flags.writeable:
                            arr = arr.copy()
                        arr[by1:by2, bx1:bx2] = self._bg_buffer[by1:by2, bx1:bx2]

            yield arr, index / self.fps
            index += 1

            target_time += interval
            delay = target_time - time.perf_counter()
            if delay > 0.001:
                time.sleep(delay)
            elif delay < -0.05:
                target_time = time.perf_counter()

    def close(self) -> None:
        self._stop.set()
        if self._fast_cap is not None:
            self._fast_cap.close()
            self._fast_cap = None


def _detect_webcam_cmd(device: str, fps: float, width: int = 640, height: int = 480) -> list[str]:
    exe = ffmpeg_exe()
    fps_str = str(int(fps))
    size_str = f"{width}x{height}"

    if str(device).lower() in ("test", "testsrc", "virtual", "none"):
        return [
            exe,
            "-f",
            "lavfi",
            "-i",
            f"testsrc=size={size_str}:rate={fps_str}",
        ]

    if os.name == "nt":
        target_device = device
        if device == "0" or not device:
            target_device = ""
            try:
                p = subprocess.run(
                    [exe, "-list_devices", "true", "-f", "dshow", "-i", "dummy"],
                    capture_output=True,
                    text=True,
                    timeout=2.0,
                )
                for line in p.stderr.splitlines():
                    if ']' in line and '"' in line and ("(video)" in line or "(none)" in line):
                        start = line.find('"') + 1
                        end = line.find('"', start)
                        if start > 0 and end > start:
                            target_device = line[start:end]
                            break
            except Exception:
                target_device = ""

        if target_device:
            try:
                test_proc = subprocess.run(
                    [
                        exe,
                        "-f",
                        "dshow",
                        "-i",
                        f"video={target_device}",
                        "-vframes",
                        "1",
                        "-f",
                        "null",
                        "-",
                    ],
                    capture_output=True,
                    timeout=2.0,
                )
                if test_proc.returncode == 0:
                    return [
                        exe,
                        "-f",
                        "dshow",
                        "-video_size",
                        size_str,
                        "-framerate",
                        fps_str,
                        "-i",
                        f"video={target_device}",
                    ]
            except Exception:
                pass
    elif sys.platform == "darwin":
        dev_idx = device if device else "0"
        return [
            exe,
            "-f",
            "avfoundation",
            "-video_size",
            size_str,
            "-framerate",
            fps_str,
            "-i",
            f"{dev_idx}:none",
        ]
    else:
        dev_path = device if device.startswith("/dev/") else f"/dev/video{device or '0'}"
        if os.path.exists(dev_path):
            return [
                exe,
                "-f",
                "v4l2",
                "-video_size",
                size_str,
                "-framerate",
                fps_str,
                "-i",
                dev_path,
            ]

    return [
        exe,
        "-f",
        "lavfi",
        "-i",
        f"testsrc=size={size_str}:rate={fps_str}",
    ]


class WebcamSource:
    def __init__(
        self,
        renderer: BaseRenderer,
        device: str = "0",
        fps: float = 30.0,
        width: int = 640,
        height: int = 480,
    ) -> None:
        self._renderer = renderer
        self.device = str(device)
        self.fps = max(1.0, float(fps))
        self.width = width
        self.height = height
        self.source_size = (width, height)
        self._stop = threading.Event()
        self._proc: subprocess.Popen | None = None
        self._thread: threading.Thread | None = None

    def frames(self) -> Iterator[Frame]:
        base_cmd = _detect_webcam_cmd(self.device, self.fps, self.width, self.height)
        cmd = base_cmd + [
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "-",
        ]
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        self._proc = proc
        frame_bytes = self.width * self.height * 3
        q: queue.Queue[np.ndarray | None] = queue.Queue(maxsize=4)
        stop = self._stop

        def reader() -> None:
            stdout = proc.stdout
            assert stdout is not None
            try:
                while not stop.is_set():
                    raw = stdout.read(frame_bytes)
                    if len(raw) < frame_bytes:
                        break
                    frame = np.frombuffer(raw, dtype=np.uint8).reshape(self.height, self.width, 3)
                    if q.full():
                        with contextlib.suppress(queue.Empty):
                            q.get_nowait()
                    with contextlib.suppress(queue.Full):
                        q.put(frame, timeout=0.05)
            finally:
                with contextlib.suppress(Exception):
                    q.put(None)

        thread = threading.Thread(target=reader, name="curlcast-webcam", daemon=True)
        self._thread = thread
        thread.start()

        index = 0
        try:
            while not stop.is_set():
                item = q.get()
                if item is None:
                    break
                yield item, index / self.fps
                index += 1
        finally:
            self.close()

    def close(self) -> None:
        self._stop.set()
        proc, self._proc = self._proc, None
        if proc is not None:
            with contextlib.suppress(Exception):
                proc.kill()
                proc.wait(timeout=1.0)
        thread, self._thread = self._thread, None
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=1.0)
