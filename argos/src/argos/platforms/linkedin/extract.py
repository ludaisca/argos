"""Extracción de LinkedIn (DOM; requiere sesión iniciada por el humano).

Los selectores siguen las clases semi-estables de LinkedIn
(``reusable-search__…``, ``feed-shared-update-v2``, ``update-components-…``) con
respaldo a los atributos ``data-view-name`` del layout nuevo.
"""

from __future__ import annotations

import re
from typing import Any

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Locator, Page

from argos.models import Post, Profile, SearchHit
from argos.platforms.parse_utils import parse_count, parse_relative_date

_BASE = "https://www.linkedin.com"

_RESULT_SELECTOR = (
    "li.reusable-search__result-container, "
    "div[data-view-name='search-entity-result-universal-template']"
)
_POST_SELECTOR = "div.feed-shared-update-v2, div[data-view-name='feed-full-update']"


def _safe_text(
    node: Locator | Page, selector: str, *, timeout: int = 1500
) -> str | None:
    try:
        locator = node.locator(selector).first
        if locator.count() == 0:
            return None
        text = locator.inner_text(timeout=timeout).strip()
        return text or None
    except PlaywrightError:
        return None


def _author_from_text(text: str | None) -> str | None:
    if not text:
        return None
    return text.split("•")[0].strip() or None


def parse_search_results(page: Page, *, kind: str, limit: int) -> list[SearchHit]:
    """Resultados de búsqueda de personas o empresas."""
    hits: list[SearchHit] = []
    nodes = page.locator(_RESULT_SELECTOR)
    try:
        count = nodes.count()
    except PlaywrightError:
        return hits
    profile_marker = "/company/" if kind == "companies" else "/in/"
    for index in range(count):
        node = nodes.nth(index)
        name = (
            _safe_text(node, "span.entity-result__title-text a span[aria-hidden='true']")
            or _safe_text(node, "a span[aria-hidden='true']")
            or _safe_text(node, "[data-anonymize='person-name']")
        )
        href = None
        try:
            link = node.locator(f"a[href*='{profile_marker}']").first
            if link.count():
                href = link.get_attribute("href")
        except PlaywrightError:
            href = None
        if not name or not href:
            continue
        url = href.split("?")[0]
        if url.startswith("/"):
            url = f"{_BASE}{url}"
        subtitle = _safe_text(node, ".entity-result__primary-subtitle") or _safe_text(
            node, "[data-anonymize='headline']"
        )
        secondary = _safe_text(node, ".entity-result__secondary-subtitle")
        username = url.rstrip("/").rsplit("/", 1)[-1]
        hits.append(
            SearchHit(
                platform="linkedin",
                type="page" if kind == "companies" else "person",
                username=username,
                name=name,
                url=url,
                followers=parse_count(secondary or subtitle),
            )
        )
        if len(hits) >= limit:
            break
    return hits


def parse_posts(page: Page, *, limit: int) -> list[Post]:
    """Publicaciones del feed (perfil, empresa o búsqueda de contenido)."""
    posts: list[Post] = []
    nodes = page.locator(_POST_SELECTOR)
    try:
        count = nodes.count()
    except PlaywrightError:
        return posts
    for index in range(count):
        node = nodes.nth(index)
        text = (
            _safe_text(node, "[data-testid='expandable-text-box']")
            or _safe_text(node, ".update-components-text")
            or _safe_text(node, ".feed-shared-text")
        )
        if not text:
            continue
        author_raw = _safe_text(
            node, ".update-components-actor__title span[aria-hidden='true']"
        ) or _safe_text(node, ".update-components-actor__name span[aria-hidden='true']")
        author = _author_from_text(author_raw)
        time_text = _safe_text(
            node, ".update-components-actor__sub-description span[aria-hidden='true']"
        ) or _safe_text(node, "time")
        try:
            link = node.locator("a[href*='/feed/update/'], a[href*='urn:li:activity']").first
            href = link.get_attribute("href") if link.count() else None
        except PlaywrightError:
            href = None
        url = None
        if href:
            url = href.split("?")[0]
            if url.startswith("/"):
                url = f"{_BASE}{url}"
        post_id = None
        if url:
            match = re.search(r"activity[-:](\d+)", url)
            post_id = match.group(1) if match else None
        reactions = parse_count(_safe_text(node, ".social-details-social-counts__reactions-count"))
        comments = parse_count(_safe_text(node, ".social-details-social-counts__comments"))
        posts.append(
            Post(
                platform="linkedin",
                id=post_id or f"li-{index}-{abs(hash(text)) % 10**8}",
                url=url or f"{_BASE}/feed/",
                caption=text[:2000],
                author=author,
                created_at=parse_relative_date(time_text),
                likes=reactions,
                comments=comments,
                media_type="unknown",
            )
        )
        if len(posts) >= limit:
            break
    return posts


def parse_profile(page: Page) -> Profile:
    """Perfil de persona o empresa (``/in/…`` o ``/company/…``)."""
    name = _safe_text(page, "h1") or _safe_text(page, ".top-card-layout__title")
    headline = _safe_text(page, "div.text-body-medium") or _safe_text(
        page, ".top-card-layout__headline"
    )
    location = _safe_text(
        page, "span.text-body-small.inline.t-black--light"
    ) or _safe_text(page, ".top-card-layout__first-subline")
    followers = None
    for selector in (
        ".org-top-card-summary-info-list__info-item",
        "span.t-black--light span:has-text('seguidores')",
        "p:has-text('seguidores')",
    ):
        text = _safe_text(page, selector)
        if text and "seguidor" in text.lower():
            followers = parse_count(text)
            break
    about = _safe_text(page, "section.summary div.display-flex.ph5.pv3 > div > span") or _safe_text(
        page, "div[data-generated-suggestion-target]"
    )
    handle = None
    match = re.search(r"/(in|company)/([^/?#]+)", page.url)
    if match:
        handle = match.group(2)
    bios = [item for item in (headline, location, about) if item]
    return Profile(
        platform="linkedin",
        username=handle or "desconocido",
        full_name=name,
        bio=" · ".join(bios) or None,
        followers=followers,
    )


def followers_from_text(text: str | None) -> int | None:
    return parse_count(text)


def is_login_wall(page: Page) -> bool:
    """¿LinkedIn nos mandó al login/authwall?"""
    if "/login" in page.url or "authwall" in page.url or "checkpoint" in page.url:
        return True
    try:
        return (
            page.locator("form.login__form, #username, input[name='session_key']").count() > 0
        )
    except PlaywrightError:
        return False


def me_name(page: Page) -> str | None:
    for selector in (
        ".global-nav__me .global-nav__primary-link-text",
        "img.global-nav__me-photo",
        "[data-testid='nav-settings']",
    ):
        node = _safe_text(page, selector)
        if node:
            return node
    return None


def any_result_text(node: Any) -> str:  # pragma: no cover - compat
    return str(node)
