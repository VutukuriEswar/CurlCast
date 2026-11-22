## What is CurlCast?

CurlCast is a high-performance terminal multimedia engine designed to render photos, animated GIFs, and high-definition video directly inside your command line in crisp, 24-bit TrueColor terminal art — complete with hardware-synchronized audio playback.

Historically, terminal media rendering has been plagued by crude monochrome character ramps, sluggish frame rates, heavy screen tearing and flickering from full-screen clears, and a complete absence of audio synchronization. Playing video in terminal environments typically required heavy system-level dependencies, complex external configurations, or popped open separate GUI windows. CurlCast reimagines terminal multimedia as a self-contained, zero-system-dependency streaming pipeline. By coupling Unicode half-block pixel pairing (`▀`) with run-length-optimized ANSI escape caching, portable embedded FFmpeg decoding via `imageio-ffmpeg`, and an audio-master clock driven directly by PortAudio (`sounddevice`), CurlCast delivers fluid 30–60+ FPS terminal video playback that stays locked to audio without drifting.

---

## Key Features

🔤 **Adaptive Luminance ASCII Art Engine**
- Translates media luminance onto an empirically balanced glyph density ramp.
- Features adaptive contrast stretching that dynamically clips scene luminance between the 1st and 99th percentiles, ensuring crisp detail in both low-key and high-key scenes.
- Implements exponential moving-average smoothing across consecutive video frames to prevent visual luminance "pumping" during scene transitions.
- Supports high-contrast artistic monochrome representation by default, with `--color` for 24-bit RGB TrueColor.

🔊 **Hardware-Synchronized, Drift-Corrected Audio Engine**
- Treats the audio hardware stream as the authoritative master clock (`audio position = stream.time - baseline - latency`).
- Video frame pacing is slaved to the active audio stream: absolute frame deadlines (`index / fps`) prevent frame jitter from accumulating into audio-video drift.
- Automatically drops late frames (more than two intervals behind) if the terminal emulator experiences heavy rendering bottlenecks, preserving perfect lipsync and audio continuity.
- Multi-tier fallback architecture: automatically probes and routes through `sounddevice` (PortAudio) → `ffplay` → `mpv` → `afplay` (macOS M4A bridge) → graceful silence with clear status logging.

⚡ **Zero-Flicker Single-Buffer Display Engine**
- Completely eliminates screen flicker and strobe artifacts by avoiding destructive terminal clears (`ESC[2J` or `cls`).
- Repaints frames in-place using cursor-home repositioning (`ESC[H`) combined with single atomic buffer writes and trailing line clearance (`ESC[J`).
- Safely manages terminal state: automatically hides the cursor on launch and guarantees cursor and virtual terminal restoration on normal exit or `Ctrl+C` interrupt via robust `finally` teardown handlers.

📐 **Sub-Pixel Geometry & Aspect Ratio Normalization**
- Corrects for standard ~2:1 vertical character cell geometry.
- Enforces strict mathematical aspect ratio constraints: preserves exact aspect ratio across all zoom levels, including adaptive compensation for micro-font cell flattening.
- Fully verified against 16:9 widescreen, 4:3 standard, 1:1 square, 9:16 vertical mobile, and ultrawide media formats.
- Automatically handles EXIF orientation metadata for mobile smartphone photos and videos.

🎞️ **Multi-Format Media Engine & Zero System Dependencies**
- Ships with zero external system requirements — no pre-installed system `ffmpeg`, `gstreamer`, or codec libraries needed. Portable FFmpeg binaries are automatically managed via `imageio-ffmpeg`.
- Full playback support for MP4, MKV, WebM, AVI, MOV, and animated GIFs.
- Dedicated GIF decoder engine via Pillow with full frame disposal method handling, localized per-frame delay timings, and alpha channel compositing.

🧩 **Pluggable & Extensible Renderer Architecture**
- Object-oriented strategy pattern based on `BaseRenderer`.
- Developers can implement custom renderers (such as Braille patterns, custom shading palettes, or colored matrix glyphs) and register them into the CLI runtime with a single decorator or function call.

🌀 **Self-Contained Generative Demos**
- Ships with built-in, pure NumPy mathematical animation sources: a colorful multi-frequency plasma field and a 3D z-buffered spinning torus.
- Allows immediate verification of terminal color capabilities, geometry budgets, and playback frame rates with zero external media files.

---

## Architecture & Media Pipeline

```
+-----------------------------------------------------------------------------+
|                                MEDIA SOURCE                                 |
|            (Video File: MP4/MKV/WebM, Animated GIF, or Image)               |
+-------------------------------------+---------------------------------------+
                                      |
                                      v
+-----------------------------------------------------------------------------+
|                          PRE-FLIGHT PROBE & GEOMETRY                        |
|   - Extract dimensions, duration, SAR/DAR, and rotation metadata            |
|   - Query terminal viewport dimensions (cols x rows) via kernel API          |
|   - Compute target bounding box enforcing 2:1 terminal cell correction      |
+-------------------------------------+---------------------------------------+
                                      |
                     +----------------+----------------+
                     |                                 |
                     v                                 v
+-----------------------------------+   +-------------------------------------+
|        AUDIO SUB-PIPELINE         |   |         VIDEO SUB-PIPELINE          |
|  - Extract audio stream via ffmpeg|   |  - ffmpeg hardware/CPU decode       |
|  - Initialize PortAudio stream    |   |  - Target-scale via Lanczos filter  |
|  - Start hardware playback clock  |   |  - Stream raw RGB24 into pipe       |
+--------------------+--------------+   +------------------+------------------+
                     |                                     |
                     | Audio Master Clock                  | Raw RGB Frames
                     | (stream.time - latency)             | (bounded queue)
                     |                                     |
                     +---------------->+<------------------+
                                       |
                                       v
+-----------------------------------------------------------------------------+
|                         PACING & DRIFT-CORRECTION LOOP                      |
|   - Compute deadline: target_pts = index / target_fps                       |
|   - Query delta against master audio position                               |
|   - Drop frame if > 2 intervals behind; sleep if ahead of schedule          |
+--------------------------------------+--------------------------------------+
                                       |
                                       v
+-----------------------------------------------------------------------------+
|                          ACTIVE RENDERER STRATEGY                           |
|                      [ASCII Mode: Glyph Density Engine]                     |
|                      - Adaptive contrast stretch                            |
|                      - Dynamic LUT glyph mapping & quantization             |
|                      - In-place run-length ANSI escape emission             |
+-----------------------------------------------------------------------------+
                                       |
                                       v
+-----------------------------------------------------------------------------+
|                      ZERO-FLICKER ATOMIC TERMINAL SINK                      |
|   - ESC[H (Home Cursor) + Encoded Frame Buffer + ESC[J (Clear Remaining)   |
|   - Single atomic standard output write per frame                           |
+-----------------------------------------------------------------------------+
```

### Directory Structure

```text
src/curlcast/
├── __init__.py          # Package version (__version__) and public metadata
├── __main__.py          # python -m curlcast invocation entrypoint
├── cli.py               # Typer CLI application (view, play, demo commands)
├── terminal.py          # Win32/POSIX terminal setup, sizing, flicker-free Screen
├── ffmpeg.py            # Bundled portable ffmpeg binary resolver & ffprobe parser
├── player.py            # Media frame decoders, bounded queues, drift-corrected loop
├── audio.py             # PortAudio (sounddevice) stream manager & fallback engines
├── demo.py              # Self-contained NumPy plasma and 3D torus generators
├── py.typed             # PEP 561 static typing marker
└── renderers/
    ├── __init__.py      # Renderer registry (register_renderer, get_renderer)
    ├── base.py          # BaseRenderer abstract strategy & fit() geometry engine
    ├── _pixels.py       # High-performance NumPy color quantization & helpers
    └── ascii.py         # Adaptive contrast ASCII art renderer
```

---

## Tech Stack

**Core Engine & CLI:**
- **Python 3.10+** (Modern typed Python with strict static typing)
- **Typer & Rich** (Ergonomic CLI command routing, argument parsing, and styled console feedback)

**Video & Media Processing:**
- **imageio-ffmpeg** (Bundles portable, self-contained FFmpeg binaries with zero system installation)
- **Pillow (PIL)** (Image decoding, EXIF orientation correction, and animated GIF frame extraction)
- **NumPy** (Vectorized RGB frame manipulation, contrast clipping, and generative mathematical demos)

**Audio Engine & Synchronization:**
- **sounddevice & PortAudio** (Low-latency asynchronous audio streaming and hardware-level master clock)
- **ffplay / mpv / afplay** (Resilient secondary and platform-native audio fallbacks)

**Terminal Graphics & System Integration:**
- **ANSI 24-Bit TrueColor** (Full RGB `38;2;r;g;b` and `48;2;r;g;b` color gamut)
- **Windows Virtual Terminal Processing** (`kernel32` Win32 API bridge enabling UTF-8 and VT escape sequences on Windows consoles)
- **Single-Buffer In-Place Repainting** (`ESC[H` cursor-home repaint eliminating full-screen clear flicker)

**Testing & Quality Assurance:**
- **Pytest** (Comprehensive test suite spanning aspect ratios, geometry, decoders, audio clocks, and CLI)
- **Ruff** (Blazing-fast linting and code formatting)
- **Mypy** (Strict type verification across all modules)

---

## Quick Start Guide

### Prerequisites
- **Python ≥ 3.10**
- A terminal with **24-bit TrueColor** support:
  - **Windows:** Windows Terminal (strongly recommended) or Windows 10+ standard console (`conhost.exe`).
  - **macOS:** iTerm2, Kitty, Ghostty, Alacritty, or Terminal.app.
  - **Linux / WSL2:** GNOME Terminal, Konsole, Alacritty, Kitty, WezTerm, etc.
- An audio output device (optional; video playback automatically falls back to silence if no audio device is present).

### Installation Options

#### Option A: Install from PyPI (Recommended)

```bash
pip install curlcast
```

#### Option B: Install from Source (Development / Editable)

```bash
# 1. Clone repository
git clone https://github.com/VutukuriEswar/CurlCast.git
cd CurlCast

# 2. Set up virtual environment
python -m venv .venv

# On Windows:
.venv\Scripts\activate
# On macOS / Linux:
# source .venv/bin/activate

# 3. Install in editable mode with development dependencies
pip install -e ".[dev]"
```

### Verification (Instant Demo)

Test your terminal's TrueColor capabilities and playback engine instantly without downloading any media files:

```bash
curlcast demo
```

To run the 3D spinning torus in ASCII mode:

```bash
curlcast demo --animation torus --mode ascii
```

---

## CLI Commands & Usage Reference

### 1. View Static Images (`curlcast view`)

Renders a still photo or graphic in the terminal and exits cleanly.

```bash
# Render image in default high-contrast artistic monochrome ASCII
curlcast view photo.jpg

# Render with 24-bit TrueColor enabled
curlcast view photo.jpg --color

# Constrain output width to 120 character columns
curlcast view photo.jpg --width 120

# Render without upscaling smaller images
curlcast view logo.png --no-upscale
```

| Option | Flag | Default | Description |
|---|---|---|---|
| `--mode` | `-m` | `ascii` | Renderer mode (`ascii`). |
| `--width` | `-w` | `0` (auto) | Output width in columns (`0` automatically fits terminal width). |
| `--color` | — | `False` | Enables 24-bit RGB TrueColor output (default: monochrome). |
| `--no-upscale` | — | `False` | Prevents enlarging images smaller than the terminal viewport. |

---

### 2. Play Videos & GIFs (`curlcast play`)

Plays a video or animated GIF in real time with synchronized audio.

```bash
# Play video with synchronized audio (monochrome ASCII)
curlcast play movie.mp4

# Play video with full TrueColor enabled
curlcast play movie.mp4 --color

# Play video capped at 30 FPS
curlcast play movie.mp4 --fps 30

# Loop an animated GIF continuously
curlcast play animation.gif --loop

# Play video muted
curlcast play clip.mp4 --no-audio
```

| Option | Flag | Default | Description |
|---|---|---|---|
| `--mode` | `-m` | `ascii` | Renderer mode (`ascii`). |
| `--width` | `-w` | `0` (auto) | Output width in columns (`0` automatically fits terminal width). |
| `--fps` | — | `20.0` | Target frame rate (1.0 to 120.0 FPS, capped at media source rate). |
| `--loop` | `-l` | `False` | Loops playback continuously until stopped. |
| `--no-audio` | — | `False` | Disables audio playback stream. |
| `--color` | — | `False` | Enables 24-bit RGB TrueColor output (default: monochrome). |

> **Playback Control:** Press **`Ctrl+C`** at any point to stop playback. CurlCast intercepts interrupts to restore cursor visibility, terminate audio streams, and cleanly kill background decoder processes.

---

### 3. Generative Demos (`curlcast demo`)

Runs a real-time mathematical animation generated on-the-fly using NumPy arrays.

```bash
# Run default plasma wave animation for 10 seconds
curlcast demo

# Run 3D z-buffered spinning torus for 30 seconds
curlcast demo --animation torus --duration 30

# Run plasma animation infinitely (press Ctrl+C to exit)
curlcast demo --duration 0
```

| Option | Flag | Default | Description |
|---|---|---|---|
| `--animation` | `-a` | `plasma` | Generative animation type: `plasma` or `torus`. |
| `--mode` | `-m` | `ascii` | Renderer mode (`ascii`). |
| `--width` | `-w` | `0` (auto) | Output width in columns (`0` fits terminal). |
| `--fps` | — | `24.0` | Target animation frame rate (1.0 to 60.0 FPS). |
| `--duration` | `-d` | `10.0` | Duration in seconds (`0` runs indefinitely until `Ctrl+C`). |
| `--color` | — | `False` | Enables TrueColor output (default: monochrome). |

---

## How It Works (Engineering Deep Dive)

### 1. Pixel Geometry & Aspect Ratio Normalization

Standard terminal character cells are not square — they are approximately twice as tall as they are wide (~2:1 aspect ratio). Directly mapping one image pixel to one character cell results in extreme vertical stretching.

CurlCast solves this through geometry scaling in `BaseRenderer`:
- Sampling half as many vertical character rows naturally counteracts the 2:1 character cell elongation.
- Includes dynamic cell aspect compensation for micro-font sizes at maximum terminal zoom-out, preventing horizontal pancake distortion.

### 2. Audio-Master Clock & Drift Correction

In real-time multimedia playback, video decoding and terminal rendering speeds fluctuate based on CPU load and terminal emulator throughput. If video is paced by software sleeps alone, it will rapidly drift out of sync with audio.

CurlCast designates the **PortAudio hardware stream** as the authoritative timekeeper:

$$\text{Audio Position} = T_{\text{stream}} - T_{\text{baseline}} - \Delta_{\text{latency}}$$

1. **Hardware Priming:** `audio.prepare()` opens the audio device before the first video frame is processed. `audio.start()` begins playback as soon as frame 0 is buffered.
2. **Absolute Deadlines:** Every video frame is assigned an absolute presentation timestamp ($\text{PTS} = \frac{\text{frame\_index}}{\text{FPS}}$).
3. **Adaptive Frame Dropping:** If terminal rendering lags and the audio position exceeds the frame deadline by more than 2 full intervals, the frame is immediately dropped. The decoder jumps forward to catch up with the audio clock. Audio is never interrupted, stuttered, or desynced.

### 3. Zero-Flicker Single-Buffer Repainting

Traditional terminal programs execute `os.system("clear")` or emit `ESC[2J` before printing each frame. This forces the terminal emulator to blank the entire display buffer, causing unbearable visual flashing and strobing.

CurlCast implements a non-destructive repaint loop:
1. Emits `ESC[H` to return the cursor to row 1, column 1 without clearing the screen buffer.
2. Formats the entire frame into a single pre-allocated string in memory.
3. Writes the complete frame buffer in **one atomic write operation** to `sys.stdout`.
4. Emits `ESC[J` at the end of the frame buffer to wipe any remaining lines from previous frames if the terminal was resized or if the video height decreased.

### 4. TrueColor Run-Length ANSI Optimization

Emitting 24-bit TrueColor ANSI escape sequences for every single cell is computationally expensive:
`\033[38;2;R;G;Bm\033[48;2;R;G;Bm▀` requires 38 bytes per cell. On a 160×50 grid, that equates to ~304 KB per frame, choking the terminal's I/O pipe.

CurlCast optimizes this with **color-run caching**:
- Video frames naturally exhibit horizontal color coherence (adjacent pixels frequently share identical or similar colors).
- The TrueColor ASCII renderer tracks the currently active foreground color keys.
- Escape codes are emitted **only when the color actually transitions**. Identical adjacent characters reuse the current active ANSI style, compressing ANSI stream volume and boosting playback FPS.

---

## Extensibility: Creating Custom Renderers

CurlCast is built around an open, extensible renderer architecture. You can easily create and register your own custom terminal renderer:

```python
import numpy as np
from PIL import Image
from curlcast.renderers import BaseRenderer, register_renderer, get_renderer


class BrailleRenderer(BaseRenderer):
    """Custom renderer utilizing Unicode 2x4 Braille dot matrices."""
    PIXEL_ASPECT = 2.0  # Defines sampling aspect ratio

    def render(self, frame: np.ndarray) -> str:
        height, width, _ = frame.shape
        lines = []
        for y in range(0, height - 1, 2):
            row_chars = []
            for x in range(width):
                row_chars.append("⣿")
            lines.append("".join(row_chars))
        return "\n".join(lines)


register_renderer("braille", BrailleRenderer)

renderer = get_renderer("braille", width=100)
output = renderer.render_image(Image.open("photo.jpg"))
print(output)
```

Once registered, your renderer can also be invoked directly through the CLI:

```bash
curlcast play video.mp4 --mode braille
```

---

## Performance & Benchmarks

Benchmarked on an Intel Core i7 Windows machine (Python 3.11) running Windows Terminal:

| Mode | Resolution Grid | Render Latency | Max Throughput | Target Headroom |
|---|---|---|---|---|
| **ASCII Monochrome** | 120 × 60 cells | ~1 ms / frame | **~1000 FPS** | 50× at 20 FPS |
| **ASCII TrueColor** (`--color`) | 120 × 60 cells | ~6 ms / frame | **~160 FPS** | 8.0× at 20 FPS |

*Note: CurlCast's dynamic frame-dropping engine ensures that even if you target 60 FPS on a constrained terminal, audio playback remains completely uninterrupted while video smoothly drops surplus frames.*

---

## Troubleshooting

**Half-block characters show up as `?`, boxes, or garbled mojibake on Windows:**
- CurlCast automatically invokes Win32 `SetConsoleOutputCP(65001)` and sets `ENABLE_VIRTUAL_TERMINAL_PROCESSING`.
- However, legacy console fonts may lack Unicode block glyphs. Ensure your terminal font is set to **Cascadia Mono**, **Consolas**, **JetBrains Mono**, or **Fira Code**.
- For the best experience on Windows, use [Windows Terminal](https://aka.ms/terminal).

**No sound during video playback:**
- Confirm your media file actually possesses an audio stream:
  ```bash
  python -c "from curlcast.ffmpeg import probe_media; print(probe_media('video.mp4'))"
  ```
- Inspect available audio backends detected on your system:
  ```bash
  python -c "from curlcast.audio import available_backends; print(available_backends())"
  ```
- If your system does not have PortAudio drivers installed, install `ffplay` or `mpv` on your system PATH as an automatic secondary fallback.

**Image appears horizontally or vertically stretched:**
- Terminal cells are assumed to possess a 2:1 height-to-width ratio. CurlCast automatically handles this and dynamically adjusts for extreme terminal zoom levels.
- Small images may appear pixelated when enlarged to fill the window; pass `--no-upscale` to render them at natural dimensions.

**Screen wraps or produces extra blank lines:**
- CurlCast intentionally reserves the final character column and bottom row to prevent line wrapping on terminals with strict bounds.
- If your terminal wrapper still forces wrap, manually set `--width` to 2 columns less than your terminal width (e.g. `--width 118`).

**Terminal cursor remained hidden after an abnormal crash:**
- While `Screen.close()` runs inside a strict `finally` block, an abrupt process termination can occasionally leave the cursor hidden.
- To restore the cursor:
  - On macOS/Linux: run `tput cnorm` or `reset`.
  - On Windows: simply open a new terminal tab or run `echo -e "\033[?25h"`.

---

## Development & Testing

### Running the Test Suite

CurlCast features a comprehensive test suite (115+ automated tests) validating aspect ratio geometry, color caches, ANSI escapes, audio drift correction, and CLI subcommands:

```bash
# Run tests with Pytest
python -m pytest

# Run Ruff linter and formatter checks
ruff check src tests

# Run strict Mypy static type verification
mypy src
```

### Manual Smoke Testing

Generate a synthetic media file containing an active video test pattern and a 440 Hz audio tone to test all playback features:

```bash
# Generate 10-second test video with 440Hz sine wave audio
ffmpeg -f lavfi -i testsrc2=size=1280x720:rate=30 \
       -f lavfi -i sine=frequency=440 -t 10 \
       -c:v libx264 -pix_fmt yuv420p -c:a aac sample.mp4

# Verify playback in ASCII mode
curlcast play sample.mp4
curlcast play sample.mp4 --color --loop
```

---

## Publishing to PyPI

CurlCast uses modern `hatchling` build packaging with version tracking managed in `src/curlcast/__init__.py`.

```bash
# Build wheel and source distributions
pip install build twine
python -m build

# Validate distribution packages
twine check dist/*

# Publish to PyPI
twine upload dist/*
```

Automated continuous deployment is handled by `.github/workflows/pypi-publish.yml` using PyPI **Trusted Publishing** (OIDC) whenever a `v*` git tag is pushed.

---

## License

This project is licensed under the **MIT License** — see the [LICENSE](./LICENSE) file for details.

© 2026 Eswar Vutukuri

---

## Acknowledgments

Special thanks to:
- **[imageio-ffmpeg](https://github.com/imageio/imageio-ffmpeg)** and the **[FFmpeg](https://ffmpeg.org/)** team for providing rock-solid, portable media decoding.
- **[PortAudio](http://www.portaudio.com/)** and the **[sounddevice](https://python-sounddevice.readthedocs.io/)** team for low-latency cross-platform audio streaming.
- **[NumPy](https://numpy.org/)** and **[Pillow](https://python-pillow.org/)** for foundational high-speed numerical array and image processing.
- **[Typer](https://typer.tiangolo.com/)** and **[Rich](https://github.com/Textualize/rich)** for modern, delightful terminal CLI experiences.
- The open-source terminal graphics community for pioneering TrueColor and Unicode character art rendering.
