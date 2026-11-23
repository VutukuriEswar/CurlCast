from __future__ import annotations

from typing import Any, cast

from curlcast.renderers.ascii import AsciiRenderer
from curlcast.renderers.base import BaseRenderer, RenderMode
from curlcast.renderers.effects import DitherMode, ShaderMode

__all__ = [
    "AsciiRenderer",
    "BaseRenderer",
    "DitherMode",
    "RenderMode",
    "ShaderMode",
    "available_modes",
    "get_renderer",
    "register_renderer",
]

_REGISTRY: dict[str, type[BaseRenderer]] = {}


def register_renderer(name: str, renderer: type[BaseRenderer]) -> None:
    key = name.strip().lower()
    if not key:
        raise ValueError("renderer name must not be empty")
    if not issubclass(renderer, BaseRenderer):
        raise TypeError("renderer must subclass BaseRenderer")
    _REGISTRY[key] = renderer


def available_modes() -> list[str]:
    return sorted(_REGISTRY)


def get_renderer(
    mode: str | RenderMode = "ascii",
    width: int = 0,
    color: bool = True,
    rows: int = 0,
    shader: ShaderMode | str = ShaderMode.NONE,
    dither: DitherMode | str = DitherMode.NONE,
    anaglyph: bool = False,
    text: str | None = None,
) -> BaseRenderer:

    key = mode.value if isinstance(mode, RenderMode) else str(mode).strip().lower()
    try:
        renderer = _REGISTRY[key]
    except KeyError:
        raise ValueError(
            f"unknown render mode {key!r}; available: {', '.join(available_modes())}"
        ) from None
    factory: Any = renderer
    try:
        return cast(
            BaseRenderer,
            factory(
                width=width,
                color=color,
                rows=rows,
                shader=shader,
                dither=dither,
                anaglyph=anaglyph,
                text=text,
            ),
        )
    except TypeError:
        return cast(BaseRenderer, factory(width=width, color=color, rows=rows))


register_renderer(RenderMode.ASCII.value, AsciiRenderer)
