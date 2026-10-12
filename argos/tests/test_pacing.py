"""Ritmo: rangos de espera, scroll y determinismo con RNG inyectado."""

from __future__ import annotations

import random

import pytest

from argos.browser.pacing import Pacer


class FakeMouse:
    def __init__(self) -> None:
        self.wheels: list[tuple[float, float]] = []

    def wheel(self, delta_x: float, delta_y: float) -> None:
        self.wheels.append((delta_x, delta_y))


class FakePage:
    def __init__(self) -> None:
        self.mouse = FakeMouse()


def make_pacer() -> tuple[Pacer, list[float]]:
    slept: list[float] = []
    pacer = Pacer(
        dwell_range=(3.0, 9.0),
        short_range=(1.5, 4.0),
        scroll_range=(600, 900),
        rng=random.Random(42),
        sleep_fn=slept.append,
    )
    return pacer, slept


def test_dwell_bounds_and_count() -> None:
    pacer, slept = make_pacer()
    for _ in range(10):
        pacer.dwell()
    assert len(slept) == 10
    assert all(3.0 <= value <= 9.0 for value in slept)


def test_short_bounds() -> None:
    pacer, slept = make_pacer()
    for _ in range(10):
        pacer.short()
    assert all(1.5 <= value <= 4.0 for value in slept)


def test_scroll_wheel_and_pauses() -> None:
    pacer, slept = make_pacer()
    page = FakePage()
    pacer.scroll(page, steps=3)  # type: ignore[arg-type]

    assert len(page.mouse.wheels) == 3
    for delta_x, delta_y in page.mouse.wheels:
        assert delta_x == 0
        assert 600 <= delta_y <= 900
    assert len(slept) == 3


def test_scroll_with_zero_steps_is_noop() -> None:
    pacer, slept = make_pacer()
    page = FakePage()
    pacer.scroll(page, steps=0)  # type: ignore[arg-type]
    assert page.mouse.wheels == []
    assert slept == []


def test_invalid_bounds_raise() -> None:
    pacer = Pacer(dwell_range=(9.0, 3.0), sleep_fn=lambda _s: None)
    with pytest.raises(ValueError, match="rango"):
        pacer.dwell()


def test_zero_sleep_is_skipped() -> None:
    slept: list[float] = []
    pacer = Pacer(sleep_fn=slept.append)
    pacer.sleep(0)
    pacer.sleep(-1)
    assert slept == []
