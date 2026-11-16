# CurlCast 🎬

> Render any **photo, GIF, or video** directly inside your terminal in crisp,
> high-definition terminal art — with synced audio.

```console
pip install curlcast
curlcast demo
```

No media file, no system `ffmpeg`, no config: `demo` generates a colourful
NumPy animation so you can verify the install immediately.

---

## Features

| Feature | Detail |
|---|---|
| **HD block mode** (default) | Unicode `▀` with 24-bit TrueColor — two pixels per character cell, doubling vertical resolution |
| **ASCII mode** | 70-glyph density ramp with adaptive contrast and optional per-glyph truecolor |
| **Synced audio** | ffmpeg → PortAudio streaming (sounddevice), with `ffplay` / `mpv` / `afplay` fallbacks |
| **Drift-corrected playback** | Audio-master clock, absolute frame deadlines, late-frame dropping |
| **Zero-flicker** | Cursor-home repaint (`ESC[H`), no full-screen clears, `ESC[J` cleanup |
| **True aspect ratio** | 2:1 cell correction for ASCII, 1:1 pixel pairs for HD |
| **GIF support** | Per-frame delays and correct compositing via Pillow |
| **Built-in demo** | Plasma and z-buffered spinning torus, generated with NumPy |
| **No system ffmpeg** | `imageio-ffmpeg` bundles a portable ffmpeg binary |
| **Plug-in renderers** | `BaseRenderer` strategy interface + public registry |

---

## Requirements

- **Python ≥ 3.10**
- A terminal with **24-bit TrueColor** (Windows Terminal, iTerm2, most modern
  Linux terminals). Legacy `conhost` works on Windows 10+ because CurlCast
  enables UTF-8 output and virtual terminal processing itself.
- Audio is optional; `sounddevice` ships with the package and bundles PortAudio.

---

## Installation

```console
pip install curlcast
```

From source (editable):

```console
git clone https://github.com/yourusername/curlcast.git
cd curlcast
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS / Linux
pip install -e ".[dev]"
```

---

## Usage

### View a still image

```console
curlcast view photo.jpg
curlcast view photo.jpg --mode ascii
curlcast view photo.jpg --width 120
curlcast view logo.png --no-color --no-upscale
```

`view` applies EXIF orientation (phone photos appear upright), fits the image
inside the terminal without distortion, and never hides the cursor.

| Option | Default | Description |
|---|---|---|
| `--mode`, `-m` | `hd` | `hd` (half blocks) or `ascii` |
| `--width`, `-w` | terminal width − 1 | Output width in character columns (`0` = auto) |
| `--no-color` | off | Monochrome output |
| `--no-upscale` | off | Do not enlarge images smaller than the terminal |

### Play a video or GIF

```console
curlcast play video.mp4
curlcast play video.mp4 --mode ascii --fps 30
curlcast play video.mp4 --loop --no-audio
curlcast play animation.gif --loop
```

| Option | Default | Description |
|---|---|---|
| `--mode`, `-m` | `hd` | `hd` or `ascii` |
| `--width`, `-w` | terminal width − 1 | Output width in columns (`0` = auto) |
| `--fps` | `20` | Display rate, capped at the source rate (1–120) |
| `--loop`, `-l` | off | Restart when the file ends |
| `--no-audio` | off | Mute |
| `--no-color` | off | Monochrome output |

Press **Ctrl+C** to stop. The cursor is always restored, audio is terminated,
and the decoder process is cleaned up.

### Run the demo

```console
curlcast demo
curlcast demo --animation torus --duration 30
curlcast demo --mode ascii --duration 0
```

`--duration 0` runs until Ctrl+C. `--animation` accepts `plasma` (default) or
`torus`.

### Other

```console
curlcast --version
curlcast --help
python -m curlcast demo        # same CLI without the console script
```

---

## How it works

### Renderers own geometry and encoding

`PIXEL_ASPECT` is the number of sampled pixel **rows per character row**, and it
is the whole aspect-ratio story:

| Mode | Sampling grid | Why |
|---|---|---|
| `hd` | `cols × (rows × 2)` | Each `▀` cell paints a 1×2 pixel pair, so pixels stay square |
| `ascii` | `cols × rows` | A glyph cell is already ~2:1 tall, so one glyph per pixel restores the aspect |

Getting ASCII backwards is the classic bug: it emits twice the requested rows
and stretches the picture vertically. The test suite asserts output never
exceeds the terminal budget for 16:9, 4:3, 1:1, 9:16 and ultrawide sources.

**HD encoding** uses foreground colour for the top pixel and background colour
for the bottom pixel. Both escape sequences are cached by packed colour and
only re-emitted when the colour changes between neighbouring cells; video has
long horizontal runs, so this is several times faster than formatting two
escapes per cell. `--no-color` keeps the full 2-pixel resolution using `' '`,
`▀`, `▄` and `█`.

**ASCII encoding** clips luminance to its 2nd–98th percentile before mapping to
the 70-character ramp, with exponential smoothing across frames so video does
not visibly "pump" when the scene changes.

### Video pipeline

```
ffmpeg -re -i clip.mp4 -an
       -vf fps=<min(source, target)>,scale=<w>:<h>:flags=lanczos,setsar=1
       -f rawvideo -pix_fmt rgb24 -
```

1. `ffmpeg` (bundled by `imageio-ffmpeg`) decodes **already scaled** frames, so
   Python never touches a 4K frame.
2. A decoder thread reads exact-size frame buffers and pushes them into a small
   bounded queue; backpressure protects memory, and the render loop drops
   frames that are more than two intervals late.
3. Frame deadlines are absolute (`index / fps`), so render jitter never
   accumulates into drift.
4. Frames are painted with `ESC[H` + frame + `ESC[J`, in one write per frame.
   The cursor is hidden on entry and restored in `finally`.

### Audio pipeline

The audio **is the clock**. PortAudio's stream time (minus its output latency)
tells the renderer which media timestamp should be on screen right now:

```
audio position = stream.time - baseline - stream.latency
```

`prepare()` opens the device before the first frame is decoded and `start()`
begins playback once frame 1 is ready, so device initialisation cannot skip the
opening seconds. `position()` drives video pacing, which keeps audio and video
locked even when rendering is slow.

Backend order: `sounddevice` → `ffplay` → `mpv` → `afplay` (macOS, via a
temporary M4A) → silence (one warning). GIFs and files without an audio stream
skip the audio stack entirely.

---

## Architecture

```text
src/curlcast/
├── __init__.py          # version and public metadata
├── __main__.py          # python -m curlcast
├── cli.py               # Typer commands: view / play / demo
├── terminal.py          # ANSI setup, terminal sizing, flicker-free Screen
├── ffmpeg.py            # bundled binary lookup + media probing
├── player.py            # frame sources, decoder threads, pacing loop
├── audio.py             # audio backends + audio-master clock
├── demo.py              # NumPy plasma and torus sources
├── py.typed             # PEP 561 marker
└── renderers/
    ├── __init__.py      # registry: register_renderer / get_renderer
    ├── base.py          # BaseRenderer strategy + fit() geometry
    ├── _pixels.py       # shared NumPy helpers
    ├── blocks.py        # --mode hd
    └── ascii.py         # --mode ascii
```

## Adding your own renderer

A renderer receives an `(H, W, 3)` `uint8` RGB array and returns terminal text.
Set `PIXEL_ASPECT` to match your cell geometry, then register it:

```python
import numpy as np

from curlcast.renderers import BaseRenderer, register_renderer


class BrailleRenderer(BaseRenderer):
    PIXEL_ASPECT = 1.0  # one sample row per character row

    def render(self, frame: np.ndarray) -> str:
        # frame.shape == (height, width, 3)
        ...


register_renderer("braille", BrailleRenderer)
```

```console
curlcast play video.mp4 --mode braille
```

`register_renderer` replaces an existing name if you want to override a built-in
for a session. Renderers can also be used directly:

```python
from PIL import Image
from curlcast.renderers import get_renderer

renderer = get_renderer("hd", width=100)
print(renderer.render_image(Image.open("photo.jpg"), upscale=True))
```

---

## Performance

Measured on a Windows laptop (Python 3.11) with a 120×45 terminal:

| Mode | Grid | Render time | Budget |
|---|---|---|---|
| `hd` | 120 × 68 | ~14 ms/frame | 70 fps |
| `hd` | 178 × 100 | ~35 ms/frame | 28 fps |
| `ascii` | 80 × 45 | ~10 ms/frame | 100 fps |

The default 20 fps has comfortable headroom. On a slower terminal the player
drops late frames rather than drifting away from the audio.

---

## Troubleshooting

**Blocks look like `?` or mojibake on Windows.**
Use Windows Terminal (recommended) or Windows 10+ `conhost`. CurlCast calls
`SetConsoleOutputCP(65001)` and enables `ENABLE_VIRTUAL_TERMINAL_PROCESSING`,
but a font without block glyphs will still show boxes — Cascadia Mono, Consolas
and most programming fonts are fine.

**No sound.**
`curlcast --help` does not report audio status. Check that the file has an audio
stream, then install a system player (`ffplay` or `mpv`) as a fallback. Run
`python -c "from curlcast.audio import available_backends; print(available_backends())"`
to see what is usable.

**The image looks stretched.**
Terminal cells are assumed to be 2:1. Fonts with unusual cell ratios (some
CJK fonts) can differ; `--mode hd` is closest to 1:1 because it encodes pixels
in pairs. `--no-upscale` also helps when a small image is being enlarged.

**Output wraps / adds a blank line.**
CurlCast reserves the last column and bottom row. If your terminal has an
unusual width, pass an explicit `--width` two columns narrower than the window.

**Ctrl+C left the cursor hidden.**
This should not happen (`Screen.close()` runs in `finally`), but any terminal
can be restored with `tput cnorm` (macOS/Linux) or by reopening the tab.

---

## Development

```console
pip install -e ".[dev]"

python -m pytest            # 115 tests
ruff check src tests
mypy src
```

The test suite covers geometry budgets and aspect ratios for both modes,
ANSI/colour invariants, the 70-character ramp, adaptive contrast, GIF timing,
real ffmpeg decoding (a synthetic clip is generated with the bundled binary),
probe parsing (including rotation metadata), pacing/drop behaviour, audio clock
semantics, cursor restoration, packaging metadata, and every CLI command.

### Manual smoke test

Generate a clip with audio and a GIF, then try both modes:

```console
ffmpeg -f lavfi -i testsrc2=size=1280x720:rate=30 ^
       -f lavfi -i sine=frequency=440 -t 10 ^
       -c:v libx264 -pix_fmt yuv420p -c:a aac sample.mp4

curlcast play sample.mp4
curlcast play sample.mp4 --mode ascii --loop
curlcast demo --animation torus
```

---

## Publishing to PyPI

The package name `curlcast` is available on PyPI as of this release. The version
lives in exactly one place — `__version__` in `src/curlcast/__init__.py` — and
hatchling reads it from there, so a release is just a tag.

```console
pip install build twine
python -m build               # dist/curlcast-<version>.tar.gz + wheel
twine check dist/*
```

Publish to TestPyPI first:

```console
twine upload --repository testpypi dist/*
pip install -i https://test.pypi.org/simple/ \
    --extra-index-url https://pypi.org/simple/ curlcast
```

Then to PyPI (use an API token: username `__token__`):

```console
twine upload dist/*
pip install curlcast
```

### Automated releases

`.github/workflows/pypi-publish.yml` publishes on `v*` tags using PyPI
**Trusted Publishing** (OIDC), so no API token is stored in the repository.
Configure the publisher once in the PyPI project settings:

- Owner/repository: your GitHub account and repo
- Workflow: `pypi-publish.yml`
- Environment: `pypi`

```console
git tag v0.1.0
git push origin v0.1.0
```

---

## License

MIT © 2026 CurlCast Contributors. See [LICENSE](LICENSE).
