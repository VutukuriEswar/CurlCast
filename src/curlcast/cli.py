from __future__ import annotations

import contextlib
import sys
from pathlib import Path

import typer
from PIL import Image, ImageOps
from rich.console import Console

from curlcast import __version__
from curlcast.demo import DemoAnimation, run_demo
from curlcast.renderers import RenderMode, get_renderer
from curlcast.terminal import configure_streams

_IMAGES = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"}
_MEDIA = {".mp4", ".mov", ".webm", ".mkv", ".gif", ".avi", ".m4v"}

app = typer.Typer(
    name="curlcast",
    help=(
        "Render photos, GIFs, and videos in crisp terminal art — with synced audio.\n\n"
        "[bold]Examples[/]\n\n"
        "  curlcast view photo.jpg --mode ascii\n\n"
        "  curlcast play video.mp4 --loop\n\n"
        "  curlcast demo --animation torus"
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


def _renderer(mode: RenderMode, width: int, no_color: bool):
    try:
        return get_renderer(mode, width=width, color=not no_color)
    except ValueError as exc:
        err.print(f"[red]error[/] {exc}")
        raise typer.Exit(code=1) from exc


@app.command()
def view(
    image_path: Path = typer.Argument(..., metavar="IMAGE", help="Image file to render."),
    mode: RenderMode = typer.Option(
        RenderMode.HD, "--mode", "-m", help="Render mode.", case_sensitive=False
    ),
    width: int = typer.Option(
        0, "--width", "-w", min=0, help="Output width in columns (0 = fit terminal)."
    ),
    no_color: bool = typer.Option(False, "--no-color", help="Monochrome output."),
    no_upscale: bool = typer.Option(
        False, "--no-upscale", help="Never enlarge images smaller than the terminal."
    ),
) -> None:

    _require_file(image_path, _IMAGES)

    try:
        with Image.open(image_path) as opened:
            image = ImageOps.exif_transpose(opened).convert("RGB")
            image.load()
    except (OSError, ValueError) as exc:
        err.print(f"[red]error[/] cannot read image: {exc}")
        raise typer.Exit(code=1) from exc

    renderer = _renderer(mode, width, no_color)
    art = renderer.render_image(image, upscale=not no_upscale)

    try:
        sys.stdout.write(art + "\n")
        sys.stdout.flush()
    except BrokenPipeError:
        raise typer.Exit(code=0) from None


@app.command()
def play(
    media_path: Path = typer.Argument(..., metavar="MEDIA", help="Video or GIF to play."),
    mode: RenderMode = typer.Option(
        RenderMode.HD, "--mode", "-m", help="Render mode.", case_sensitive=False
    ),
    width: int = typer.Option(
        0, "--width", "-w", min=0, help="Output width in columns (0 = fit terminal)."
    ),
    fps: float = typer.Option(
        20.0, "--fps", min=1.0, max=120.0, help="Target frame rate (capped at source fps)."
    ),
    loop: bool = typer.Option(False, "--loop", "-l", help="Loop until interrupted."),
    no_audio: bool = typer.Option(False, "--no-audio", help="Disable audio playback."),
    no_color: bool = typer.Option(False, "--no-color", help="Monochrome output."),
) -> None:
    _require_file(media_path, _MEDIA)

    renderer = _renderer(mode, width, no_color)

    from curlcast.ffmpeg import MediaError
    from curlcast.player import play as play_media

    try:
        play_media(media_path, renderer, fps=fps, loop=loop, muted=no_audio)
    except MediaError as exc:
        err.print(f"[red]error[/] {exc}")
        raise typer.Exit(code=1) from exc
    except KeyboardInterrupt:
        raise typer.Exit(code=130) from None


@app.command()
def demo(
    mode: RenderMode = typer.Option(
        RenderMode.HD, "--mode", "-m", help="Render mode.", case_sensitive=False
    ),
    width: int = typer.Option(
        0, "--width", "-w", min=0, help="Output width in columns (0 = fit terminal)."
    ),
    duration: float = typer.Option(
        10.0, "--duration", "-d", min=0.0, help="Demo length in seconds (0 = forever)."
    ),
    fps: float = typer.Option(24.0, "--fps", min=1.0, max=60.0, help="Animation frame rate."),
    animation: DemoAnimation = typer.Option(
        DemoAnimation.PLASMA, "--animation", "-a", help="Animation to display."
    ),
    no_color: bool = typer.Option(False, "--no-color", help="Monochrome output."),
) -> None:

    renderer = _renderer(mode, width, no_color)
    with contextlib.suppress(KeyboardInterrupt):
        run_demo(renderer, duration=duration, fps=fps, animation=animation)


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
