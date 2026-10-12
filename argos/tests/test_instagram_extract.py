"""Extracción de Instagram contra capturas reales recortadas (sin red)."""

from __future__ import annotations

from datetime import UTC, datetime

from playwright.sync_api import Page

from argos.platforms.instagram.extract import (
    is_private_page,
    parse_comments,
    parse_count,
    parse_grid,
    parse_post_page,
    parse_profile,
    parse_search_panel,
)


def test_parse_count_variants() -> None:
    assert parse_count("5,960") == 5960
    assert parse_count("5.960") == 5960
    assert parse_count("538K") == 538_000
    assert parse_count("1.2M") == 1_200_000
    assert parse_count("686M") == 686_000_000
    assert parse_count("12") == 12
    assert parse_count("hola") is None
    assert parse_count(None) is None


def test_parse_profile_from_real_fixture(loaded_page) -> None:
    page: Page = loaded_page("ig_profile.html")
    profile = parse_profile(page, "instagram")

    assert profile.username == "instagram"
    assert profile.full_name == "Instagram"
    assert profile.followers == 687_000_000
    assert profile.following == 303
    assert profile.posts_count == 8608
    assert profile.bio == "Discover what's new on Instagram 🔎✨"
    assert profile.is_verified is True
    assert profile.is_private is False
    assert profile.profile_pic_url is not None
    assert profile.profile_pic_url.startswith("https://")


def test_parse_grid_from_real_fixture(loaded_page) -> None:
    page: Page = loaded_page("ig_profile.html")
    posts = parse_grid(page, limit=10, author="instagram")

    assert len(posts) == 4  # el fixture recortado conserva 4 anchors
    assert len({post.id for post in posts}) == 4  # sin duplicados
    first = posts[0]
    assert first.id
    assert first.url.startswith("https://www.instagram.com/instagram/p/")
    assert first.caption  # el alt de la imagen trae (parte de) el caption
    assert len(first.caption) < 500
    assert "http" not in first.caption.lower()  # nunca debe mezclar el src
    assert first.author == "instagram"
    assert first.thumbnail_url is not None
    assert first.thumbnail_url.startswith("https://")

    assert len(parse_grid(page, limit=2, author="instagram")) == 2


def test_parse_post_page_from_real_fixture(loaded_page) -> None:
    page: Page = loaded_page("ig_post.html")
    url = "https://www.instagram.com/instagram/p/Ddr-AMmDxqn/"
    post = parse_post_page(page, url=url, author="instagram")

    assert post.id == "Ddr-AMmDxqn"
    assert post.likes == 538_000
    assert post.comments == 5960
    assert post.created_at == datetime(2026, 9, 24, 22, 40, 5, tzinfo=UTC)
    assert post.author == "instagram"
    assert post.caption is not None
    assert post.caption.startswith("Catching all the news from Meta Connect")
    assert post.thumbnail_url is not None


def test_private_page_detection(loaded_page) -> None:
    page: Page = loaded_page("ig_profile.html")
    assert is_private_page(page) is False


def test_parse_grid_from_hashtag_fixture(loaded_page) -> None:
    page: Page = loaded_page("ig_hashtag.html")
    posts = parse_grid(page, limit=10, author=None)

    assert len(posts) == 4
    assert all(post.author is None for post in posts)
    assert any(post.media_type == "video" for post in posts)  # hay anclas con <video>
    for post in posts:
        assert post.thumbnail_url is None or post.thumbnail_url.startswith("http")


def test_parse_grid_from_reels_fixture(loaded_page) -> None:
    page: Page = loaded_page("ig_reels.html")
    posts = parse_grid(page, limit=10, author="nasa")

    assert len(posts) == 4
    assert all("/reel/" in post.url for post in posts)
    assert all(post.media_type == "video" for post in posts)
    assert all(post.thumbnail_url for post in posts)  # vienen del background-image
    first = posts[0]
    assert first.likes == 94_900  # "94.9K"
    assert first.comments == 820
    assert first.views == 4_700_000  # "4.7M"


def test_parse_reel_page_fixture(loaded_page) -> None:
    page: Page = loaded_page("ig_reel.html")
    url = "https://www.instagram.com/nasa/reel/Dd1gQBsCWE8/"
    post = parse_post_page(page, url=url, author="nasa")

    assert post.id == "Dd1gQBsCWE8"
    assert post.media_type == "video"
    assert post.likes == 95_000
    assert post.comments == 820
    assert post.created_at == datetime(2026, 9, 28, 15, 27, 10, tzinfo=UTC)
    assert post.caption is not None
    assert "asteroid" in post.caption.lower()


def test_parse_search_panel_fixture(loaded_page) -> None:
    page: Page = loaded_page("ig_search_panel.html")
    hits = parse_search_panel(page, limit=10)

    assert len(hits) >= 3
    assert all(hit.type == "user" for hit in hits)
    first = hits[0]
    assert first.username == "nasa"
    assert first.name == "NASA"
    assert first.followers == 104_000_000
    assert first.url == "https://www.instagram.com/nasa/"
    # los links del footer no deben colarse
    assert all("popular" not in (hit.url or "") for hit in hits)


def test_parse_comments_fixture(loaded_page) -> None:
    page: Page = loaded_page("ig_comments.html")
    comments = parse_comments(
        page,
        post_url="https://www.instagram.com/instagram/p/Ddr-AMmDxqn/",
        limit=5,
    )

    assert len(comments) >= 3
    assert all(comment.author for comment in comments)
    assert all(comment.text for comment in comments)
    assert all(comment.id.isdigit() for comment in comments)
    assert all(comment.post_url.endswith("/Ddr-AMmDxqn/") for comment in comments)
    first = comments[0]
    assert first.age_text is not None
    assert first.created_at is not None
    assert first.created_at < datetime.now(UTC)


def test_parse_comments_handles_edited_suffix(loaded_page) -> None:
    page: Page = loaded_page("ig_comment_edited.html")
    comments = parse_comments(
        page,
        post_url="https://www.instagram.com/p/ABC/",
        limit=5,
    )

    assert len(comments) == 1
    comment = comments[0]
    assert comment.author == "alguien"
    assert comment.text == "Texto del comentario"
    assert comment.age_text == "3d · Edited"
    assert comment.created_at is not None
