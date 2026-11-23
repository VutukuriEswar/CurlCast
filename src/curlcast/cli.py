from __future__ import annotations

import contextlib
import sys
from pathlib import Path
from typing import Any

import typer
from PIL import Image, ImageOps
from rich.console import Console

from curlcast import __version__
from curlcast.lyrics import LyricEngine
from curlcast.renderers import DitherMode, ShaderMode, get_renderer
from curlcast.renderers.normal import Flashlight
from curlcast.terminal import (
    Screen,
    configure_streams,
    get_size,
    is_tty,
    poll_input,
)

_IMAGES = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"}
_MEDIA = {".mp4", ".mov", ".webm", ".mkv", ".gif", ".avi", ".m4v"}

app = typer.Typer(
    name="curlcast",
    help=(
        "Render photos, GIFs, and videos in crisp terminal art — with synced audio.\n\n"
        "[bold]Examples[/]\n\n"
        "  curlcast view photo.jpg\n\n"
        "  curlcast play video.mp4 --loop\n\n"
        "  curlcast cam\n\n"
        "  curlcast screen --region left"
    ),
    add_completion=False,
    rich_markup_mode="rich",
    pretty_exceptions_show_locals=False,
)

err = Console(stderr=True)


def _require_file(path: Path, allowed: set[str]) -> None:
    if not path.exists():
        err.print(f"[red]error[/] file not found: [bold]{path}[/]")
        raise typer.Exit(code=1)
    if not path.is_file():
        err.print(f"[red]error[/] not a file: [bold]{path}[/]")
        raise typer.Exit(code=1)
    suffix = path.suffix.lower()
    if suffix not in allowed:
        supported = ", ".join(sorted(allowed))
        err.print(
            f"[red]error[/] unsupported file type [bold]{suffix or '(none)'}[/]\n"
            f"  supported: {supported}"
        )
        raise typer.Exit(code=1)


def _renderer(
    width: int,
    color: bool,
    shader: ShaderMode = ShaderMode.NONE,
    dither: DitherMode = DitherMode.NONE,
    anaglyph: bool = False,
    text: str | None = None,
):
    try:
        return get_renderer(
            "ascii",
            width=width,
            color=color,
            shader=shader,
            dither=dither,
            anaglyph=anaglyph,
            text=text,
        )
    except ValueError as exc:
        err.print(f"[red]error[/] {exc}")
        raise typer.Exit(code=1) from exc


@app.command()
def view(
    image_path: Path = typer.Argument(..., metavar="IMAGE", help="Image file to render."),
    width: int = typer.Option(
        0, "--width", "-w", min=0, help="Output width in columns (0 = fit terminal)."
    ),
    color: bool = typer.Option(False, "--color", help="Enable color output (default: black & white)."),
    shader: ShaderMode = typer.Option(
        ShaderMode.NONE, "--shader", "-s", help="Retro aesthetic shader.", case_sensitive=False
    ),
    dither: DitherMode = typer.Option(
        DitherMode.NONE, "--dither", help="Dithering engine (bayer or floyd).", case_sensitive=False
    ),
    anaglyph: bool = typer.Option(
        False, "--3d", "--anaglyph", help="Red-Cyan stereoscopic 3D mode."
    ),
    flashlight: bool = typer.Option(
        False, "--flashlight", help="Interactive 2.5D flashlight with dynamic surface normals."
    ),
    text: str = typer.Option(
        "", "--text", "-t", help="Custom phrase for typographic ASCII rendering."
    ),
    no_upscale: bool = typer.Option(
        False, "--no-upscale", help="Never enlarge images smaller than the terminal."
    ),
    once: bool = typer.Option(
        False, "--once", "-1", help="Print once to stdout and exit without interactive viewer."
    ),
) -> None:
    fl = Flashlight(auto_sweep=True) if flashlight else None

    _require_file(image_path, _IMAGES)

    active_text: str | None = None
    if text:
        text_str = text.strip()
        text_path = Path(text_str)
        if text_path.is_file():
            active_text = text_path.read_text(encoding="utf-8", errors="replace")
        elif any(
            text_str.lower().endswith(ext)
            for ext in (".srt", ".lrc", ".txt", ".sub")
        ) or ("\\" in text_str or "/" in text_str):
            err.print(f"[red]error[/] text file not found: [bold]{text_str}[/]")
            raise typer.Exit(code=1)
        else:
            active_text = text_str

    try:
        with Image.open(image_path) as opened:
            image = ImageOps.exif_transpose(opened).convert("RGB")
            image.load()
    except (OSError, ValueError) as exc:
        err.print(f"[red]error[/] cannot read image: {exc}")
        raise typer.Exit(code=1) from exc

    import numpy as np

    if not is_tty() or once:
        renderer = _renderer(
            width,
            color,
            shader=shader,
            dither=dither,
            anaglyph=anaglyph,
            text=active_text,
        )
        display_img = Image.fromarray(fl.apply_light(np.asarray(image))) if fl else image
        art = renderer.render_image(display_img, upscale=not no_upscale)
        try:
            sys.stdout.write(art + "\n")
            sys.stdout.flush()
        except BrokenPipeError:
            raise typer.Exit(code=0) from None
        return

    renderer = _renderer(
        width,
        color,
        shader=shader,
        dither=dither,
        anaglyph=anaglyph,
        text=active_text,
    )
    screen = Screen()
    try:
        with screen:
            last_size = (0, 0)
            animating = bool(flashlight)
            import time
            start_t = time.perf_counter()
            while True:
                size = get_size()
                curr_size = (size.columns, size.rows)
                size_changed = curr_size != last_size
                if size_changed or animating:
                    last_size = curr_size
                    if size_changed:
                        renderer.refresh_size()
                    if fl:
                        fl.update_time(time.perf_counter() - start_t)
                        display_img = Image.fromarray(fl.apply_light(np.asarray(image)))
                    else:
                        display_img = image
                    art = renderer.render_image(display_img, upscale=not no_upscale)
                    screen.draw(art)

                key = poll_input(timeout=0.04 if animating else 0.08)
                if key == "EXIT":
                    break
                elif fl is not None and key is not None:
                    if key == "UP":
                        fl.move(0.0, -0.06)
                    elif key == "DOWN":
                        fl.move(0.0, 0.06)
                    elif key == "LEFT":
                        fl.move(-0.06, 0.0)
                    elif key == "RIGHT":
                        fl.move(0.06, 0.0)
    except KeyboardInterrupt:
        pass


@app.command()
def play(
    media_path: Path = typer.Argument(..., metavar="MEDIA", help="Video or GIF to play."),
    width: int = typer.Option(
        0, "--width", "-w", min=0, help="Output width in columns (0 = fit terminal)."
    ),
    fps: float = typer.Option(
        20.0, "--fps", min=1.0, max=120.0, help="Target frame rate (capped at source fps)."
    ),
    loop: bool = typer.Option(False, "--loop", "-l", help="Loop until interrupted."),
    no_audio: bool = typer.Option(False, "--no-audio", help="Disable audio playback."),
    color: bool = typer.Option(False, "--color", help="Enable color output (default: black & white)."),
    shader: ShaderMode = typer.Option(
        ShaderMode.NONE, "--shader", "-s", help="Retro aesthetic shader.", case_sensitive=False
    ),
    dither: DitherMode = typer.Option(
        DitherMode.NONE, "--dither", help="Dithering engine (bayer or floyd).", case_sensitive=False
    ),
    anaglyph: bool = typer.Option(
        False, "--3d", "--anaglyph", help="Red-Cyan stereoscopic 3D mode."
    ),
    flashlight: bool = typer.Option(
        False, "--flashlight", help="Interactive 2.5D flashlight with dynamic surface normals."
    ),
    text: str = typer.Option(
        "", "--text", "-t", help="Custom phrase, or path to .srt/.lrc/.txt file for typographic rendering."
    ),
    serve: int = typer.Option(
        0, "--serve", help="Local HTTP port to broadcast stream to curl clients."
    ),
) -> None:
    fl = Flashlight(auto_sweep=True) if flashlight else None

    _require_file(media_path, _MEDIA)

    text_engine = None
    active_text: str | None = None
    if text:
        text_str = text.strip()
        text_path = Path(text_str)
        if text_path.is_file():
            text_engine = LyricEngine(text_path)
            active_text = text_engine.get_line(0.0)
        elif any(
            text_str.lower().endswith(ext)
            for ext in (".srt", ".lrc", ".txt", ".sub")
        ) or ("\\" in text_str or "/" in text_str):
            err.print(f"[red]error[/] text file not found: [bold]{text_str}[/]")
            raise typer.Exit(code=1)
        else:
            text_engine = LyricEngine(text_str)
            active_text = text_str

    renderer = _renderer(
        width,
        color,
        shader=shader,
        dither=dither,
        anaglyph=anaglyph,
        text=active_text,
    )

    from curlcast.ffmpeg import MediaError
    from curlcast.player import play as play_media

    try:
        play_media(
            media_path,
            renderer,
            fps=fps,
            loop=loop,
            muted=no_audio,
            lyrics=text_engine,
            flashlight=fl,
            serve=serve,
        )
    except MediaError as exc:
        err.print(f"[red]error[/] {exc}")
        raise typer.Exit(code=1) from exc
    except KeyboardInterrupt:
        raise typer.Exit(code=130) from None


@app.command()
def cam(
    device: str = typer.Argument("0", help="Webcam device index or name."),
    width: int = typer.Option(
        0, "--width", "-w", min=0, help="Output width in columns (0 = fit terminal)."
    ),
    fps: float = typer.Option(30.0, "--fps", min=1.0, max=60.0, help="Camera frame rate."),
    color: bool = typer.Option(False, "--color", help="Enable color output (default: black & white)."),
    shader: ShaderMode = typer.Option(
        ShaderMode.NONE, "--shader", "-s", help="Retro aesthetic shader.", case_sensitive=False
    ),
    dither: DitherMode = typer.Option(
        DitherMode.NONE, "--dither", help="Dithering engine (bayer or floyd).", case_sensitive=False
    ),
    anaglyph: bool = typer.Option(
        False, "--3d", "--anaglyph", help="Red-Cyan stereoscopic 3D mode."
    ),
    flashlight: bool = typer.Option(
        False, "--flashlight", help="Interactive 2.5D flashlight with dynamic surface normals."
    ),
    serve: int = typer.Option(
        0, "--serve", help="Local HTTP port to broadcast stream to curl clients."
    ),
) -> None:
    renderer = _renderer(
        width,
        color,
        shader=shader,
        dither=dither,
        anaglyph=anaglyph,
    )
    from curlcast.capture import WebcamSource
    from curlcast.player import PerfClock, render_loop
    from curlcast.server import StreamServer

    fl = Flashlight(auto_sweep=True) if flashlight else None
    srv = StreamServer(port=serve) if serve > 0 else None
    if srv:
        srv.start()

    source = WebcamSource(renderer, device=device, fps=fps)
    screen = Screen()
    try:
        with screen:
            renderer.refresh_size()
            render_loop(
                source.frames(),
                renderer,
                screen,
                PerfClock(),
                fps,
                source_size=source.source_size,
                flashlight=fl,
                server=srv,
                live=True,
            )
    except KeyboardInterrupt:
        pass
    finally:
        source.close()
        if srv:
            srv.stop()


@app.command()
def screen(
    region: str = typer.Option(
        "", "--region", help="Screen region to capture: 'left', 'right', 'top', 'bottom', or 'x,y,w,h'."
    ),
    width: int = typer.Option(
        0, "--width", "-w", min=0, help="Output width in columns (0 = fit terminal)."
    ),
    fps: float = typer.Option(30.0, "--fps", min=1.0, max=60.0, help="Screen capture frame rate."),
    color: bool = typer.Option(False, "--color", help="Enable color output (default: black & white)."),
    shader: ShaderMode = typer.Option(
        ShaderMode.NONE, "--shader", "-s", help="Retro aesthetic shader.", case_sensitive=False
    ),
    dither: DitherMode = typer.Option(
        DitherMode.NONE, "--dither", help="Dithering engine (bayer or floyd).", case_sensitive=False
    ),
    anaglyph: bool = typer.Option(
        False, "--3d", "--anaglyph", help="Red-Cyan stereoscopic 3D mode."
    ),
    flashlight: bool = typer.Option(
        False, "--flashlight", help="Interactive 2.5D flashlight with dynamic surface normals."
    ),
    serve: int = typer.Option(
        0, "--serve", help="Local HTTP port to broadcast stream to curl clients."
    ),
) -> None:
    renderer = _renderer(
        width,
        color,
        shader=shader,
        dither=dither,
        anaglyph=anaglyph,
    )
    from curlcast.capture import ScreenSource, WindowManager
    from curlcast.player import PerfClock, render_loop
    from curlcast.server import StreamServer

    fl = Flashlight(auto_sweep=True) if flashlight else None
    srv = StreamServer(port=serve) if serve > 0 else None
    if srv:
        srv.start()

    win_mgr = WindowManager(region=region)
    clean_shot = win_mgr.setup()
    import time
    time.sleep(0.06)
    renderer.refresh_size()

    source = ScreenSource(
        renderer,
        fps=fps,
        region=region,
        window_mgr=win_mgr,
        initial_bg=clean_shot,
    )
    term_screen = Screen()
    try:
        with term_screen:
            renderer.refresh_size()
            render_loop(
                source.frames(),
                renderer,
                term_screen,
                PerfClock(),
                fps,
                source_size=source.source_size,
                flashlight=fl,
                server=srv,
                live=True,
            )
    except KeyboardInterrupt:
        pass
    finally:
        source.close()
        win_mgr.restore()
        if srv:
            srv.stop()


@app.command()
def broadcast(
    target: str = typer.Argument(..., metavar="TARGET", help="Media file, 'cam', or 'screen' to broadcast."),
    port: int = typer.Option(8080, "--port", "-p", min=1024, max=65535, help="HTTP streaming port."),
    width: int = typer.Option(
        80, "--width", "-w", min=10, help="Stream column width."
    ),
    color: bool = typer.Option(True, "--color", help="Enable color output."),
    shader: ShaderMode = typer.Option(
        ShaderMode.NONE, "--shader", "-s", help="Retro aesthetic shader.", case_sensitive=False
    ),
    dither: DitherMode = typer.Option(
        DitherMode.NONE, "--dither", help="Dithering engine (bayer or floyd).", case_sensitive=False
    ),
    anaglyph: bool = typer.Option(
        False, "--3d", "--anaglyph", help="Red-Cyan stereoscopic 3D mode."
    ),
    fps: float = typer.Option(24.0, "--fps", min=1.0, max=60.0, help="Stream frame rate."),
) -> None:
    renderer = _renderer(
        width,
        color,
        shader=shader,
        dither=dither,
        anaglyph=anaglyph,
    )
    from curlcast.capture import ScreenSource, WebcamSource
    from curlcast.player import FFmpegSource, GifSource, PerfClock, render_loop
    from curlcast.server import StreamServer

    srv = StreamServer(port=port)
    srv.start()
    err.print("[bold green]Streaming active![/] Clients can connect with:")
    err.print(f"  [bold cyan]curl -sN http://localhost:{port}[/]\n")

    lower = target.lower()
    source: Any
    is_live = False
    if lower == "cam":
        source = WebcamSource(renderer, fps=fps)
        is_live = True
    elif lower == "screen":
        source = ScreenSource(renderer, fps=fps)
        is_live = True
    else:
        path = Path(target)
        _require_file(path, _MEDIA)
        if path.suffix.lower() == ".gif":
            source = GifSource(path, renderer)
        else:
            from curlcast.ffmpeg import probe_media
            info = probe_media(path)
            source = FFmpegSource(path, renderer, info, fps)

    term_screen = Screen()
    try:
        with term_screen:
            renderer.refresh_size()
            render_loop(
                source.frames(),
                renderer,
                term_screen,
                PerfClock(),
                fps,
                source_size=source.source_size,
                server=srv,
                live=is_live,
            )
    except KeyboardInterrupt:
        pass
    finally:
        source.close()
        srv.stop()


@app.callback(invoke_without_command=True)
def _root(
    ctx: typer.Context,
    version: bool = typer.Option(
        False,
        "--version",
        "-V",
        help="Show the version and exit.",
        is_eager=True,
    ),
) -> None:
    configure_streams()
    if version:
        typer.echo(f"curlcast {__version__}")
        raise typer.Exit()
    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())
        raise typer.Exit()


def main() -> None:
    configure_streams()
    app()


if __name__ == "__main__":
    main()
