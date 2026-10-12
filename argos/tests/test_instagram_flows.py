"""Flujos de lectura contra fixtures locales: límites, acciones y cortes."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path

import pytest

from argos.browser.pacing import Pacer
from argos.errors import UsageError
from argos.platforms.instagram import (
    fetch_comments,
    fetch_hashtag,
    fetch_posts,
    fetch_profile,
    fetch_reels,
    normalize_hashtag,
    normalize_post_url,
    normalize_username,
    parse_since,
    search,
)

FIXTURES = Path(__file__).parent / "fixtures"


class FixtureSession:
    """Sesión duck-typed que sirve fixtures locales en lugar de navegar."""

    def __init__(
        self,
        page,
        profile_html: str | None = None,
        post_fixture: str = "ig_post.html",
    ) -> None:
        self._page = page
        self._profile_html = profile_html or (
            FIXTURES / "ig_profile.html"
        ).read_text(encoding="utf-8")
        self._post_html = (FIXTURES / post_fixture).read_text(encoding="utf-8")
        self.visited: list[str] = []

    @property
    def page(self):
        return self._page

    def _html_for(self, url: str) -> str:
        if re.search(r"/(?:p|reel)/", url):
            return self._post_html
        if "/reels/" in url:
            return (FIXTURES / "ig_reels.html").read_text(encoding="utf-8")
        if "/explore/tags/" in url or "/explore/search/keyword/" in url:
            return (FIXTURES / "ig_hashtag.html").read_text(encoding="utf-8")
        if url.rstrip("/") == "https://www.instagram.com":
            return self._home_html()
        return self._profile_html

    def _home_html(self) -> str:
        """Home sintético: ícono de búsqueda + el contenedor real de resultados."""
        panel = (FIXTURES / "ig_search_panel.html").read_text(encoding="utf-8")
        body = re.search(r"<main>(.*)</main>", panel, re.S)
        inner = body.group(1) if body else ""
        return (
            "<!DOCTYPE html><html><head><title>Instagram</title></head><body>"
            "<button><svg aria-label='Search' width='24' height='24'></svg></button>"
            "<input aria-label='Search input' type='text' style='width:200px;height:24px'>"
            f"<main>{inner}</main></body></html>"
        )

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


def make_limiter() -> CountingLimiter:
    return CountingLimiter()


def test_normalize_username_variants() -> None:
    assert normalize_username("@nasa") == "nasa"
    assert normalize_username(" nasa ") == "nasa"
    assert normalize_username("https://www.instagram.com/nasa/") == "nasa"
    with pytest.raises(UsageError):
        normalize_username("no vale!")


def test_parse_since() -> None:
    assert parse_since("2026-09-01") == datetime(2026, 9, 1, tzinfo=UTC)
    assert parse_since("2026-09-01T12:30:00+00:00") == datetime(
        2026, 9, 1, 12, 30, tzinfo=UTC
    )
    with pytest.raises(UsageError):
        parse_since("01/09/2026")


def test_fetch_profile_limits_and_counts_actions(browser_page) -> None:
    session = FixtureSession(browser_page)
    limiter = make_limiter()
    result = fetch_profile(
        session, "@instagram", limiter=limiter, pacer=make_pacer(), limit=2
    )

    assert result.profile.username == "instagram"
    assert len(result.recent_posts) == 2
    assert result.actions == 1  # una sola navegación, sin scrolls
    assert limiter.calls == 1


def test_fetch_profile_scrolls_are_capped(browser_page) -> None:
    session = FixtureSession(browser_page)
    limiter = make_limiter()
    # El fixture tiene 4 posts y no crece: pedir 36 no debe colgar ni scrollear 6 veces.
    result = fetch_profile(
        session, "instagram", limiter=limiter, pacer=make_pacer(), limit=36
    )

    assert len(result.recent_posts) == 4
    assert result.actions == 2  # navegación + 1 scroll sin crecimiento
    assert limiter.calls == 2


def test_fetch_posts_with_details(browser_page) -> None:
    session = FixtureSession(browser_page)
    limiter = make_limiter()
    result = fetch_posts(
        session,
        "instagram",
        limiter=limiter,
        pacer=make_pacer(),
        limit=2,
        details=True,
    )

    assert len(result.posts) == 2
    first = result.posts[0]
    assert first.likes == 538_000
    assert first.comments == 5960
    assert first.created_at == datetime(2026, 9, 24, 22, 40, 5, tzinfo=UTC)
    assert result.actions == 3  # navegación + 2 posts visitados
    assert [url for url in session.visited].count("https://www.instagram.com/instagram/") == 1


def test_fetch_posts_without_details(browser_page) -> None:
    session = FixtureSession(browser_page)
    limiter = make_limiter()
    result = fetch_posts(
        session,
        "instagram",
        limiter=limiter,
        pacer=make_pacer(),
        limit=2,
        details=False,
    )

    assert len(result.posts) == 2
    assert result.posts[0].likes is None  # sin visitar el post
    assert result.actions == 1


def test_fetch_posts_since_stops_early(browser_page) -> None:
    session = FixtureSession(browser_page)
    limiter = make_limiter()
    result = fetch_posts(
        session,
        "instagram",
        limiter=limiter,
        pacer=make_pacer(),
        limit=4,
        details=True,
        since=datetime(2026, 10, 1, tzinfo=UTC),
    )

    assert result.posts == []
    assert result.stopped_at_since is True
    assert result.actions == 2  # navegación + primer post (más viejo que since)


def test_fetch_posts_private_account(browser_page) -> None:
    private_html = (
        "<!DOCTYPE html><html><head>"
        "<meta property='og:description' content='10 Followers, 5 Following, 3 Posts "
        "- See Instagram photos and videos from Privada (@privada)'>"
        "</head><body>This account is private</body></html>"
    )
    session = FixtureSession(browser_page, profile_html=private_html)
    result = fetch_posts(
        session, "privada", limiter=make_limiter(), pacer=make_pacer(), limit=4
    )

    assert result.posts == []
    assert result.note is not None
    assert "privada" in result.note


def test_normalize_hashtag_variants() -> None:
    assert normalize_hashtag("#astrophotography") == "astrophotography"
    assert normalize_hashtag(" astrophotography ") == "astrophotography"
    assert normalize_hashtag("https://www.instagram.com/explore/tags/nasa/") == "nasa"
    with pytest.raises(UsageError):
        normalize_hashtag("no vale!")


def test_normalize_post_url_variants() -> None:
    url = "https://www.instagram.com/nasa/p/DdHyaYAifb6/"
    assert normalize_post_url(url) == url
    assert normalize_post_url("DdHyaYAifb6") == "https://www.instagram.com/p/DdHyaYAifb6/"
    with pytest.raises(UsageError):
        normalize_post_url("https://example.com/algo")
    with pytest.raises(UsageError):
        normalize_post_url("no!")


def test_fetch_hashtag_from_fixture(browser_page) -> None:
    session = FixtureSession(browser_page)
    limiter = make_limiter()
    result = fetch_hashtag(
        session,
        "#astrophotography",
        limiter=limiter,
        pacer=make_pacer(),
        limit=3,
        details=False,
    )

    assert len(result.posts) == 3
    assert all(post.author is None for post in result.posts)
    assert result.actions == 1  # una navegación, sin scroll
    assert limiter.calls == 1


def test_fetch_hashtag_with_details(browser_page) -> None:
    session = FixtureSession(browser_page)
    result = fetch_hashtag(
        session,
        "astrophotography",
        limiter=make_limiter(),
        pacer=make_pacer(),
        limit=2,
        details=True,
    )

    assert len(result.posts) == 2
    assert all(post.likes == 538_000 for post in result.posts)  # fixture de post
    assert result.actions == 3


def test_fetch_reels_from_fixture(browser_page) -> None:
    session = FixtureSession(browser_page)
    result = fetch_reels(
        session,
        "nasa",
        limiter=make_limiter(),
        pacer=make_pacer(),
        limit=2,
        details=False,
    )

    assert len(result.posts) == 2
    assert all("/reel/" in post.url for post in result.posts)
    assert all(post.media_type == "video" for post in result.posts)
    assert result.actions == 1


def test_search_posts_from_fixture(browser_page) -> None:
    session = FixtureSession(browser_page)
    result = search(
        session, "astrophotography", limiter=make_limiter(), pacer=make_pacer(), limit=3
    )

    assert len(result.posts) == 3
    assert result.actions == 1


def test_search_users_typeahead(browser_page) -> None:
    session = FixtureSession(browser_page)
    result = search(
        session,
        "nasa",
        limiter=make_limiter(),
        pacer=make_pacer(),
        kind="users",
        limit=5,
    )

    assert len(result.hits) >= 3
    assert result.hits[0].username == "nasa"
    assert result.actions == 2  # navegación a home + consulta del typeahead


def test_search_users_variants(browser_page) -> None:
    """Con --variants se prueban varias variantes de username sin re-abrir el panel."""
    session = FixtureSession(browser_page)
    result = search(
        session,
        "Uriel Arriaga Garcia",
        limiter=make_limiter(),
        pacer=make_pacer(),
        kind="users",
        limit=30,
        variants=True,
    )

    assert len(result.hits) >= 3  # el panel estático devuelve cuentas únicas
    assert result.actions > 2  # una navegación + varias consultas tipeadas
    urls = [hit.url for hit in result.hits]
    assert len(urls) == len(set(urls))


def test_search_posts_variants(browser_page) -> None:
    session = FixtureSession(browser_page)
    result = search(
        session,
        "uriel arriaga",
        limiter=make_limiter(),
        pacer=make_pacer(),
        kind="posts",
        limit=30,
        variants=True,
    )

    assert len(result.posts) >= 3
    assert result.actions > 1


def test_fetch_comments_from_fixture(browser_page) -> None:
    session = FixtureSession(browser_page, post_fixture="ig_comments.html")
    result = fetch_comments(
        session,
        "https://www.instagram.com/instagram/p/Ddr-AMmDxqn/",
        limiter=make_limiter(),
        pacer=make_pacer(),
        limit=5,
    )

    assert len(result.comments) >= 3
    assert result.comments[0].author
    assert result.comments[0].text
    assert result.actions >= 1
