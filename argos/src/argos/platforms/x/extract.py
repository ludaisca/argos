"""Extracción de X (Twitter) por ``data-testid`` (requiere sesión del humano)."""

from __future__ import annotations

import datetime as dt
import re

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Locator, Page

from argos.models import Post, Profile
from argos.platforms.parse_utils import parse_count

_BASE = "https://x.com"
_STATUS_RE = re.compile(r"/([A-Za-z0-9_]+)/status/(\d+)")


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


def _safe_attr(node: Locator | Page, selector: str, attr: str) -> str | None:
    try:
        locator = node.locator(selector).first
        if locator.count() == 0:
            return None
        return locator.get_attribute(attr)
    except PlaywrightError:
        return None


def _metric(node: Locator, testid: str) -> int | None:
    label = _safe_attr(node, f"[data-testid='{testid}']", "aria-label")
    if label is None:
        return None
    value = parse_count(label)
    return value if value is not None else 0


def is_login_wall(page: Page) -> bool:
    if "/i/flow/login" in page.url or "/login" in page.url:
        return True
    try:
        return (
            page.locator(
                "[data-testid='loginButton'], [data-testid='signupButton'], "
                "a[href='/i/flow/signup']"
            ).count()
            > 0
        )
    except PlaywrightError:
        return False


def me_handle(page: Page) -> str | None:
    text = _safe_text(page, "[data-testid='SideNav_AccountSwitcher_Button']")
    if text:
        match = re.search(r"@([A-Za-z0-9_]+)", text)
        if match:
            return match.group(1)
    return None


def parse_profile(page: Page) -> Profile:
    handle = None
    name = None
    block = _safe_text(page, "[data-testid='UserName']")
    if block:
        tokens = block.split()
        for token in tokens:
            if token.startswith("@"):
                handle = token.lstrip("@")
                break
        name_tokens = [token for token in tokens if not token.startswith("@")]
        name = " ".join(name_tokens).strip() or None
    bio = _safe_text(page, "[data-testid='UserDescription']")
    location = _safe_text(page, "[data-testid='UserLocation']")
    website = _safe_attr(page, "[data-testid='UserUrl'] a", "href")
    followers = None
    for suffix in ("/verified_followers", "/followers"):
        text = _safe_text(page, f"a[href$='{suffix}']")
        if text and "seguidor" in text.lower():
            followers = parse_count(text)
            break
    following = None
    text = _safe_text(page, "a[href$='/following']")
    if text and "siguiendo" in text.lower():
        following = parse_count(text)
    verified = None
    try:
        verified = page.locator("svg[data-testid='icon-verified']").count() > 0
    except PlaywrightError:
        verified = None
    if handle is None:
        match = re.search(r"x\.com/([A-Za-z0-9_]+)", page.url)
        handle = match.group(1) if match else "desconocido"
    return Profile(
        platform="x",
        username=handle,
        full_name=name,
        bio=" · ".join(item for item in (bio, location) if item) or None,
        followers=followers,
        following=following,
        is_verified=verified,
        external_url=website,
    )


def parse_tweets(page: Page, *, limit: int) -> list[Post]:
    posts: list[Post] = []
    articles = page.locator("article[data-testid='tweet']")
    try:
        count = articles.count()
    except PlaywrightError:
        return posts
    for index in range(count):
        node = articles.nth(index)
        try:
            if node.locator("span:has-text('Promocionado'), span:has-text('Promoted')").count() > 0:
                continue
        except PlaywrightError:
            pass
        href = _safe_attr(node, "a[href*='/status/']", "href")
        status_id = None
        author = None
        if href:
            match = _STATUS_RE.search(href)
            if match:
                author, status_id = match.group(1), match.group(2)
        if not status_id:
            continue
        text = _safe_text(node, "[data-testid='tweetText']")
        datetime_attr = _safe_attr(node, "time", "datetime")
        created = None
        if datetime_attr:
            try:
                created = dt.datetime.fromisoformat(datetime_attr.replace("Z", "+00:00"))
            except ValueError:
                created = None
        posts.append(
            Post(
                platform="x",
                id=status_id,
                url=f"{_BASE}/{author or 'i'}/status/{status_id}",
                caption=text,
                author=author,
                created_at=created,
                likes=_metric(node, "like"),
                comments=_metric(node, "reply"),
                shares=_metric(node, "retweet"),
                media_type="unknown",
            )
        )
        if len(posts) >= limit:
            break
    return posts
