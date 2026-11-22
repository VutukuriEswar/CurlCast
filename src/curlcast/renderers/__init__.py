from __future__ import annotations

from curlcast.renderers.ascii import AsciiRenderer
from curlcast.renderers.base import BaseRenderer, RenderMode

__all__ = [
    "AsciiRenderer",
    "BaseRenderer",
    "RenderMode",
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
    mode: str | RenderMode,
    width: int = 0,
    color: bool = True,
    rows: int = 0,
) -> BaseRenderer:

    key = mode.value if isinstance(mode, RenderMode) else str(mode).strip().lower()
    try:
        renderer = _REGISTRY[key]
    except KeyError:
        raise ValueError(
            f"unknown render mode {key!r}; available: {', '.join(available_modes())}"
        ) from None
    return renderer(width=width, color=color, rows=rows)


register_renderer(RenderMode.ASCII.value, AsciiRenderer)
