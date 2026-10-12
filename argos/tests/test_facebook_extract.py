"""Extracción de Facebook contra capturas reales recortadas (sin red)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from playwright.sync_api import Page

from argos.platforms.facebook.extract import (
    parse_count_es,
    parse_fb_age,
    parse_posts,
    parse_profile,
    parse_search_results,
)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("28 mill.", 28_000_000),
        ("279 mil", 279_000),
        ("1,7 mill.", 1_700_000),
        ("133 mil", 133_000),
        ("5,960", 5960),
        ("5.960", 5960),
        ("1.2M", 1_200_000),
        ("474", 474),
        ("", None),
        ("hola", None),
        (None, None),
    ],
)
def test_parse_count_es(text: str | None, expected: int | None) -> None:
    assert parse_count_es(text) == expected


def _roughly(td: timedelta, seconds: float) -> bool:
    return abs(td.total_seconds() - seconds) < seconds * 0.05 + 60


def test_parse_fb_age_variants() -> None:
    now = datetime.now(UTC)
    age = parse_fb_age("hace 3 horas")
    assert age is not None and _roughly(now - age, 3 * 3600)
    assert _roughly(now - (parse_fb_age("hace 5 días") or now), 5 * 86400)
    assert _roughly(now - (parse_fb_age("3 hours ago") or now), 3 * 3600)
    assert _roughly(now - (parse_fb_age("ayer") or now), 86400)
    assert _roughly(now - (parse_fb_age("hace 20 minutos") or now), 20 * 60)
    assert parse_fb_age("hola") is None
    assert parse_fb_age(None) is None


def test_parse_profile_fixture(loaded_page) -> None:
    page: Page = loaded_page("fb_page.html")
    profile = parse_profile(page, "NASA")

    assert profile.username == "NASA"
    assert profile.full_name is not None
    assert "NASA" in profile.full_name
    assert profile.followers == 28_000_000
    assert profile.following == 52


def test_parse_posts_fixture(loaded_page) -> None:
    page: Page = loaded_page("fb_page.html")
    posts = parse_posts(
        page,
        limit=5,
        author_hint="NASA",
        page_url="https://www.facebook.com/NASA/",
    )

    assert len(posts) == 1
    post = posts[0]
    assert post.caption is not None
    assert "Nueva tripulación" in post.caption
    assert post.likes == 474
    assert post.comments == 21
    assert post.shares == 68
    assert post.author is not None and "NASA" in post.author
    assert post.created_at is not None
    assert _roughly(datetime.now(UTC) - post.created_at, 3 * 3600)
    assert post.url == "https://www.facebook.com/NASA/"


def test_parse_search_fixture(loaded_page) -> None:
    page: Page = loaded_page("fb_search.html")
    hits = parse_search_results(page, kind="pages", limit=4)

    assert len(hits) == 4
    first = hits[0]
    assert first.name.startswith("NASA - National")
    assert first.username == "NASA"
    assert first.followers == 28_000_000
    assert first.url == "https://www.facebook.com/NASA/"
    assert all(hit.type == "page" for hit in hits)
    assert all(hit.platform == "facebook" for hit in hits)
    # El segundo resultado tiene "279 mil seguidores".
    assert hits[1].followers == 279_000


def test_post_text_cleanup(loaded_page) -> None:
    """Se limpian "Ver más" y la duración de video del texto del post."""
    page: Page = loaded_page("fb_card_noise.html")
    posts = parse_posts(page, limit=3, author_hint=None, page_url="https://x/")

    assert len(posts) == 1
    caption = posts[0].caption or ""
    assert "Ver más" not in caption
    assert "0:07" not in caption
    assert caption.startswith("Un texto de prueba")


def test_parse_search_people_keeps_profile_id(loaded_page) -> None:
    """Los perfiles personales (profile.php?id=...) deben conservar el id."""
    page: Page = loaded_page("fb_search_people.html")
    hits = parse_search_results(page, kind="people", limit=5)

    assert len(hits) == 3
    first = hits[0]
    assert first.type == "person"
    assert first.name == "Luis Islas"
    assert first.url == "https://www.facebook.com/profile.php?id=100012345678"
    assert first.username == "100012345678"
    # Un perfil con nombre de usuario normalizado (sin query)
    assert hits[1].url == "https://www.facebook.com/luis.islas.casimiro/"
    assert hits[1].username == "luis.islas.casimiro"
    assert hits[2].url == "https://www.facebook.com/profile.php?id=100099988877"
