"""Extracción de YouTube: parsea ``ytInitialData`` (JSON de la página) + DOM de comentarios.

Enfoque: para búsquedas, canales y videos se evalúa ``window.ytInitialData`` y se
recorren recursivamente las estructuras (``videoRenderer``, ``lockupViewModel``,
``channelRenderer``), lo que aguanta cambios de layout mejor que selectores CSS.
Los comentarios, que se cargan por scroll, sí se leen del DOM.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from typing import Any

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Page

from argos.models import Comment, Post, Profile, SearchHit
from argos.platforms.parse_utils import parse_count, parse_relative_date

_YT = "https://www.youtube.com"
_INITIAL_DATA_RE = re.compile(r"ytInitialData\s*=\s*(\{.+?\})\s*;\s*(?:</script>|var\s)")
_VIDEO_ID_RE = re.compile(r"(?:v=|youtu\.be/|/shorts/|/embed/)([A-Za-z0-9_-]{11})")

_UNITS: dict[str, float] = {}


# --------------------------------------------------------------------------- #
# Helpers genéricos
# --------------------------------------------------------------------------- #

def walk(node: Any, key: str) -> Iterator[dict[str, Any]]:
    """Recorre cualquier estructura y produce los valores de ``key``."""
    if isinstance(node, dict):
        for node_key, value in node.items():
            if node_key == key:
                if isinstance(value, list):
                    for item in value:
                        if isinstance(item, dict):
                            yield item
                elif isinstance(value, dict):
                    yield value
            yield from walk(value, key)
    elif isinstance(node, list):
        for item in node:
            yield from walk(item, key)


def _runs_text(node: Any) -> str | None:
    """Texto de ``{"runs": [...]}`` / ``{"simpleText": ...}`` / ``{"content": ...}``."""
    if not isinstance(node, dict):
        return None
    simple = node.get("simpleText")
    if isinstance(simple, str):
        return simple
    content = node.get("content")
    if isinstance(content, str):
        return content
    runs = node.get("runs")
    if isinstance(runs, list):
        text = "".join(str(run.get("text") or "") for run in runs if isinstance(run, dict))
        return text or None
    return None


def video_id_from(value: str) -> str | None:
    match = _VIDEO_ID_RE.search(value)
    if match:
        return match.group(1)
    return value if re.fullmatch(r"[A-Za-z0-9_-]{11}", value) else None


def initial_data_from_html(html: str) -> dict[str, Any] | None:
    match = _INITIAL_DATA_RE.search(html)
    if not match:
        return None
    try:
        data = json.loads(match.group(1))
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def initial_data(page: Page) -> dict[str, Any] | None:
    """``window.ytInitialData`` si está; si no, regex sobre el HTML."""
    try:
        data = page.evaluate("() => window.ytInitialData ?? null")
        if isinstance(data, dict):
            return data
    except PlaywrightError:
        pass
    try:
        return initial_data_from_html(page.content())
    except PlaywrightError:
        return None


def _thumbnails_url(node: Any) -> str | None:
    thumbs = node.get("thumbnails") if isinstance(node, dict) else None
    if isinstance(node, dict):
        thumb = node.get("thumbnail") or {}
        if isinstance(thumb, dict):
            model = thumb.get("thumbnailViewModel")
            if isinstance(model, dict):
                thumbs = model.get("image", {}).get("sources") or thumbs
        if isinstance(thumb, dict) and isinstance(thumb.get("sources"), list):
            thumbs = thumb["sources"]
    if isinstance(thumbs, list) and thumbs:
        last = thumbs[-1]
        if isinstance(last, dict):
            return last.get("url")
    return None


# --------------------------------------------------------------------------- #
# Búsqueda
# --------------------------------------------------------------------------- #


def _video_from_renderer(renderer: dict[str, Any]) -> Post | None:
    video_id = renderer.get("videoId")
    if not isinstance(video_id, str):
        return None
    title = _runs_text(renderer.get("title"))
    author = _runs_text(renderer.get("ownerText") or renderer.get("longBylineText"))
    views = parse_count(_runs_text(renderer.get("viewCountText")))
    published = _runs_text(renderer.get("publishedTimeText"))
    return Post(
        platform="youtube",
        id=video_id,
        url=f"{_YT}/watch?v={video_id}",
        caption=title,
        author=author,
        created_at=parse_relative_date(published),
        views=views,
        media_type="video",
        thumbnail_url=_thumbnails_url(renderer),
    )


def _video_from_lockup(lockup: dict[str, Any]) -> Post | None:
    if str(lockup.get("contentType") or "") and "VIDEO" not in str(lockup.get("contentType")):
        return None
    video_id = lockup.get("contentId")
    if not isinstance(video_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
        return None
    metadata = lockup.get("metadata") or {}
    lockup_meta = metadata.get("lockupMetadataViewModel") or {}
    title = _runs_text(lockup_meta.get("title"))
    author = None
    views = None
    published = None
    rows = lockup_meta.get("metadata", {}).get("contentMetadataViewModel", {}).get("metadataRows")
    texts: list[str] = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        for part in row.get("metadataParts") or []:
            text = _runs_text((part or {}).get("text"))
            if text:
                texts.append(text)
    has_views_word = any(re.search(r"vista|view", text, re.I) for text in texts)
    for text in texts:
        if published is None and parse_relative_date(text) is not None:
            published = text
            continue
        if views is None:
            value = parse_count(text)
            bare_count = re.fullmatch(r"[\d.,]+\s*[kmb]?", text.strip(), re.I) is not None
            if value is not None and (has_views_word or bare_count):
                views = value
                continue
        if (
            author is None
            and re.search(r"[A-Za-zÁÉÍÓÚÑáéíóúñ]", text)
            and not re.search(r"vista|view|hace|ago", text, re.I)
        ):
            author = text
    return Post(
        platform="youtube",
        id=video_id,
        url=f"{_YT}/watch?v={video_id}",
        caption=title,
        author=author,
        created_at=parse_relative_date(published),
        views=views,
        media_type="video",
        thumbnail_url=_thumbnails_url(lockup),
    )


def parse_search_videos(data: dict[str, Any], *, limit: int) -> list[Post]:
    posts: list[Post] = []
    seen: set[str] = set()
    for renderer in walk(data, "videoRenderer"):
        post = _video_from_renderer(renderer)
        if post and post.id not in seen:
            seen.add(post.id)
            posts.append(post)
    for lockup in walk(data, "lockupViewModel"):
        post = _video_from_lockup(lockup)
        if post and post.id not in seen:
            seen.add(post.id)
            posts.append(post)
        if len(posts) >= limit:
            break
    return posts[:limit]


def parse_search_channels(data: dict[str, Any], *, limit: int) -> list[SearchHit]:
    hits: list[SearchHit] = []
    seen: set[str] = set()
    for renderer in walk(data, "channelRenderer"):
        channel_id = str(renderer.get("channelId") or "")
        title = _runs_text(renderer.get("title"))
        if not title:
            continue
        handle = None
        url = f"{_YT}/channel/{channel_id}" if channel_id else _YT
        subs = parse_count(_runs_text(renderer.get("videoCountText")))
        subscribers = parse_count(_runs_text(renderer.get("subscriberCountText")))
        endpoint = renderer.get("navigationEndpoint") or {}
        canonical = (endpoint.get("browseEndpoint") or {}).get("canonicalBaseUrl")
        if isinstance(canonical, str) and canonical.startswith("/"):
            url = f"{_YT}{canonical}"
            handle = canonical.strip("/").lstrip("@")
        if url in seen:
            continue
        seen.add(url)
        hits.append(
            SearchHit(
                platform="youtube",
                type="user",
                username=handle,
                name=title,
                url=url,
                followers=subscribers or subs,
            )
        )
        if len(hits) >= limit:
            break
    return hits


# --------------------------------------------------------------------------- #
# Canal
# --------------------------------------------------------------------------- #


def parse_channel_meta(data: dict[str, Any], handle: str) -> Profile:
    meta = next(walk(data, "channelMetadataRenderer"), {}) or {}
    for header in walk(data, "pageHeaderViewModel"):
        header_title = (
            (header.get("title") or {})
            .get("dynamicTextViewModel", {})
            .get("text", {})
            .get("content")
        )
        meta.setdefault("title", header_title)
        description = (
            header.get("description", {})
            .get("descriptionPreviewViewModel", {})
            .get("description", {})
            .get("content")
        )
        if description:
            meta.setdefault("description", description)
    subscribers = None
    for node in walk(data, "subscriberCountText"):
        subscribers = parse_count(_runs_text(node))
        if subscribers is not None:
            break
    for node in walk(data, "contentMetadataViewModel"):
        rows = node.get("metadataRows") or []
        for row in rows:
            for part in row.get("metadataParts") or []:
                text = _runs_text((part or {}).get("text"))
                if text and parse_count(text) and re.search(r"suscript|subscriber", text, re.I):
                    subscribers = parse_count(text)
    title = meta.get("title") if isinstance(meta.get("title"), str) else None
    description = meta.get("description") if isinstance(meta.get("description"), str) else None
    return Profile(
        platform="youtube",
        username=handle,
        full_name=title or handle,
        bio=description,
        followers=subscribers,
    )


def parse_channel_videos(
    data: dict[str, Any], *, limit: int, author: str | None = None
) -> list[Post]:
    posts = parse_search_videos(data, limit=limit)
    if author:
        for post in posts:
            if not post.author:
                post.author = author
    return posts


# --------------------------------------------------------------------------- #
# Video
# --------------------------------------------------------------------------- #


def parse_video_meta(data: dict[str, Any], video_id: str) -> Post:
    details: dict[str, Any] = next(walk(data, "videoPrimaryInfoRenderer"), {}) or {}
    secondary: dict[str, Any] = next(walk(data, "videoSecondaryInfoRenderer"), {}) or {}
    title = _runs_text(details.get("title")) or next(
        (_runs_text(node.get("title")) for node in walk(data, "videoMetadataViewModel")), None
    )
    author = _runs_text(secondary.get("owner", {}).get("videoOwnerRenderer", {}).get("title"))
    views = parse_count(_runs_text(details.get("viewCount")))
    published = _runs_text(details.get("dateText"))
    likes = None
    for node in walk(data, "likeButtonViewModel"):
        label = node.get("likeButtonA11y") or node.get("accessibilityText") or node.get("a11yText")
        likes = parse_count(label if isinstance(label, str) else None)
        if likes is not None:
            break
    return Post(
        platform="youtube",
        id=video_id,
        url=f"{_YT}/watch?v={video_id}",
        caption=title,
        author=author,
        created_at=parse_relative_date(published) if published else None,
        views=views,
        likes=likes,
        media_type="video",
    )


_COMMENT_SELECTORS = ("ytd-comment-thread-renderer", "ytd-comment-view-model")


def parse_comments(page: Page, *, limit: int, post_url: str) -> list[Comment]:
    comments: list[Comment] = []
    for selector in _COMMENT_SELECTORS:
        try:
            count = page.locator(selector).count()
        except PlaywrightError:
            count = 0
        if not count:
            continue
        for index in range(min(count, limit)):
            node = page.locator(selector).nth(index)
            try:
                author = node.locator("#author-text").first.inner_text(timeout=1500).strip()
            except PlaywrightError:
                author = None
            try:
                text = node.locator("#content-text").first.inner_text(timeout=1500).strip()
            except PlaywrightError:
                continue
            try:
                likes_text = (
                    node.locator("#vote-count-middle").first.inner_text(timeout=800).strip()
                )
            except PlaywrightError:
                likes_text = ""
            try:
                age_selector = ".published-time-text a, [class*='published-time']"
                age = node.locator(age_selector).first.inner_text(timeout=800).strip()
            except PlaywrightError:
                age = None
            comments.append(
                Comment(
                    platform="youtube",
                    id=f"{post_url}::{index}",
                    url=post_url,
                    post_url=post_url,
                    author=author,
                    text=text,
                    likes=parse_count(likes_text),
                    age_text=age or None,
                    created_at=parse_relative_date(age),
                )
            )
        break
    return comments
