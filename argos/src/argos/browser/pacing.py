"""Ritmo humano: esperas aleatorias y scroll incremental.

Deliberadamente separable de Playwright (Protocol) para poder testear el
comportamiento temporal con un reloj/RNG inyectados.
"""

from __future__ import annotations

import random
import time
from collections.abc import Callable
from typing import Protocol

DEFAULT_DWELL = (3.0, 9.0)
DEFAULT_SHORT = (1.5, 4.0)
DEFAULT_SCROLL = (600, 900)


class _MouseLike(Protocol):
    def wheel(self, delta_x: float, delta_y: float) -> None: ...


class PageLike(Protocol):
    @property
    def mouse(self) -> _MouseLike: ...


class Pacer:
    """Genera las pausas entre acciones para no parecer un bot."""

    def __init__(
        self,
        *,
        dwell_range: tuple[float, float] = DEFAULT_DWELL,
        short_range: tuple[float, float] = DEFAULT_SHORT,
        scroll_range: tuple[int, int] = DEFAULT_SCROLL,
        rng: random.Random | None = None,
        sleep_fn: Callable[[float], None] = time.sleep,
    ) -> None:
        self._dwell_range = dwell_range
        self._short_range = short_range
        self._scroll_range = scroll_range
        self._rng = rng or random.Random()
        self._sleep = sleep_fn

    def pick(self, bounds: tuple[float, float]) -> float:
        low, high = bounds
        if low > high:
            raise ValueError(f"rango inválido: {bounds}")
        return self._rng.uniform(low, high)

    def sleep(self, seconds: float) -> None:
        if seconds > 0:
            self._sleep(seconds)

    def dwell(self) -> None:
        """Pausa larga entre acciones de alto nivel (abrir perfil, cambiar de página)."""
        self.sleep(self.pick(self._dwell_range))

    def short(self) -> None:
        """Pausa corta entre micro-acciones (scroll, click)."""
        self.sleep(self.pick(self._short_range))

    def scroll(self, page: PageLike, steps: int = 2) -> None:
        """Scroll incremental hacia abajo con pausas cortas."""
        low, high = self._scroll_range
        for _ in range(max(0, steps)):
            delta = self._rng.randint(low, high)
            page.mouse.wheel(0, delta)
            self.short()
