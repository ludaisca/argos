"""Flujos de Facebook contra fixtures locales: límites, acciones y notas."""

from __future__ import annotations

from pathlib import Path

import pytest

import argos.platforms.facebook.flows as fb_flows
from argos.browser.pacing import Pacer
from argos.errors import UsageError
from argos.platforms.facebook import (
    fetch_group_feed,
    fetch_page,
    normalize_page,
    search,
)

FIXTURES = Path(__file__).parent / "fixtures"


class FixtureSession:
    """Sesión duck-typed que sirve fixtures locales en lugar de navegar."""

    def __init__(self, page) -> None:
        self._page = page
        self.visited: list[str] = []

    @property
    def page(self):
        return self._page

    def _html_for(self, url: str) -> str:
        if "/search/" in url:
            return (FIXTURES / "fb_search.html").read_text(encoding="utf-8")
        if "/groups/feed/" in url:
            return (FIXTURES / "fb_groups_feed_empty.html").read_text(encoding="utf-8")
        return (FIXTURES / "fb_page.html").read_text(encoding="utf-8")

    def goto(self, url: str, **_kwargs: object) -> None:
        self.visited.append(url)
        self._page.set_content(self._html_for(url), wait_until="domcontentloaded")

    def raise_if_problem(self) -> None:
        pass


class CountingLimiter:
    def __init__(self) -> None:
        self.calls = 0
        self.remaining = 100

    def before_action(self) -> int:
        self.calls += 1
        self.remaining -= 1
        return self.remaining

    def daily_remaining(self) -> int:
        return self.remaining


def make_pacer() -> Pacer:
    return Pacer(sleep_fn=lambda _seconds: None)


@pytest.fixture(autouse=True)
def fast_render(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sin esperas reales de render en los tests."""
    monkeypatch.setattr(fb_flows, "_RENDER_WAIT_MS", 50)
    monkeypatch.setattr(fb_flows, "_SETTLE_MS", 0)


def test_normalize_page_variants() -> None:
    assert normalize_page("NASA") == "NASA"
    assert normalize_page("@NASA") == "NASA"
    assert normalize_page("https://www.facebook.com/NASA/?ref=x") == "NASA"
    with pytest.raises(UsageError):
        normalize_page("no vale!")


def test_fetch_page_from_fixture(browser_page) -> None:
    session = FixtureSession(browser_page)
    limiter = CountingLimiter()
    result = fetch_page(session, "NASA", limiter=limiter, pacer=make_pacer(), limit=5)

    assert result.profile.username == "NASA"
    assert result.profile.followers == 28_000_000
    assert len(result.posts) == 1
    assert result.posts[0].likes == 474
    assert limiter.calls >= 1


def test_fetch_page_scrolls_are_capped(browser_page) -> None:
    session = FixtureSession(browser_page)
    limiter = CountingLimiter()
    result = fetch_page(session, "NASA", limiter=limiter, pacer=make_pacer(), limit=36)

    assert len(result.posts) == 1  # el fixture no crece con scroll
    assert result.actions == 2  # navegación + 1 scroll sin crecimiento
    assert limiter.calls == 2


def test_fetch_group_feed_empty(browser_page) -> None:
    session = FixtureSession(browser_page)
    result = fetch_group_feed(
        session, limiter=CountingLimiter(), pacer=make_pacer(), limit=10
    )

    assert result.posts == []
    assert result.note is not None
    assert "grupos" in result.note


def test_search_pages_from_fixture(browser_page) -> None:
    session = FixtureSession(browser_page)
    limiter = CountingLimiter()
    result = search(
        session, "nasa", limiter=limiter, pacer=make_pacer(), kind="pages", limit=4
    )

    assert len(result.hits) == 4
    assert result.hits[0].followers == 28_000_000
    assert result.actions == 1
    assert limiter.calls == 1


def test_search_invalid_kind_raises(browser_page) -> None:
    session = FixtureSession(browser_page)
    with pytest.raises(UsageError, match="tipo de búsqueda"):
        search(
            session, "nasa", limiter=CountingLimiter(), pacer=make_pacer(), kind="posts"
        )


def test_search_variants_aggregates_and_dedupes(browser_page) -> None:
    session = FixtureSession(browser_page)
    limiter = CountingLimiter()
    # Varias variantes del nombre, mismo fixture => resultados deduplicados.
    result = search(
        session,
        "Uriel Arriaga Garcia",
        limiter=limiter,
        pacer=make_pacer(),
        kind="people",
        limit=30,
        variants=True,
    )

    assert len(result.hits) == 4  # el fixture tiene 4 personas únicas
    assert result.actions > 1  # corrió más de una variante
    urls = [hit.url for hit in result.hits]
    assert len(urls) == len(set(urls))
