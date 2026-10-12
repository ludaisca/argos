"""Flujos de X (Twitter): perfil y búsqueda. Requiere sesión del humano."""

from __future__ import annotations

import contextlib
from dataclasses import dataclass, field
from urllib.parse import quote_plus

from playwright.sync_api import Error as PlaywrightError
from rich.console import Console

from argos.browser.limiter import RateLimiter
from argos.browser.pacing import Pacer
from argos.browser.session import BrowserSession
from argos.errors import LoginRequiredError, UsageError
from argos.models import Post, Profile
from argos.platforms.x.extract import is_login_wall, parse_profile, parse_tweets

_BASE = "https://x.com"
MAX_LIMIT = 50
_console = Console(stderr=True)
_LOGIN_HINT = "ejecutá `argos login x` e iniciá sesión en la ventana"


@dataclass
class ProfileResult:
    profile: Profile | None = None
    recent_posts: list[Post] = field(default_factory=list)
    actions: int = 0
    daily_remaining: int = 0
    note: str | None = None


@dataclass
class SearchResult:
    posts: list[Post] = field(default_factory=list)
    actions: int = 0
    daily_remaining: int = 0
    note: str | None = None


def normalize_handle(value: str) -> str:
    text = value.strip()
    if text.startswith("http"):
        text = text.split("x.com/", 1)[-1].split("twitter.com/", 1)[-1]
        text = text.split("/", 1)[0].split("?", 1)[0]
    return text.lstrip("@")


def _open(session: BrowserSession, url: str) -> None:
    session.goto(url)
    session.raise_if_problem()
    if is_login_wall(session.page):
        raise LoginRequiredError("X pidió login para esta página", hint=_LOGIN_HINT)
    with contextlib.suppress(PlaywrightError):
        session.page.wait_for_timeout(1500)


def fetch_profile(
    session: BrowserSession,
    value: str,
    *,
    limiter: RateLimiter,
    pacer: Pacer,
    limit: int = 12,
) -> ProfileResult:
    """Perfil + posts recientes."""
    limit = max(1, min(limit, MAX_LIMIT))
    handle = normalize_handle(value)
    if not handle:
        raise UsageError("falta el @handle o URL de X")
    actions = 0
    limiter.before_action()
    actions += 1
    _open(session, f"{_BASE}/{handle}")
    pacer.dwell()
    profile = parse_profile(session.page)
    posts = parse_tweets(session.page, limit=limit)
    scrolls = 0
    while len(posts) < limit and scrolls < 4:
        limiter.before_action()
        actions += 1
        pacer.scroll(session.page, steps=2)
        posts = parse_tweets(session.page, limit=limit)
        scrolls += 1
    _console.print(
        f"[dim]X @{handle}: perfil + {len(posts)} posts ({actions} acciones)[/dim]"
    )
    return ProfileResult(
        profile=profile,
        recent_posts=posts,
        actions=actions,
        daily_remaining=limiter.daily_remaining(),
    )


def search(
    session: BrowserSession,
    query: str,
    *,
    limiter: RateLimiter,
    pacer: Pacer,
    kind: str = "top",
    limit: int = 12,
) -> SearchResult:
    """Búsqueda de posts. ``kind``: ``top`` (destacados) o ``latest`` (recientes)."""
    limit = max(1, min(limit, MAX_LIMIT))
    if kind not in ("top", "latest", "destacados", "recientes"):
        raise UsageError(
            f"kind desconocido: {kind!r}", hint="opciones: top, latest"
        )
    live = kind in ("latest", "recientes")
    actions = 0
    limiter.before_action()
    actions += 1
    url = f"{_BASE}/search?q={quote_plus(query)}&src=typed_query"
    if live:
        url += "&f=live"
    _open(session, url)
    pacer.dwell()
    posts = parse_tweets(session.page, limit=limit)
    scrolls = 0
    while len(posts) < limit and scrolls < 4:
        limiter.before_action()
        actions += 1
        pacer.scroll(session.page, steps=2)
        posts = parse_tweets(session.page, limit=limit)
        scrolls += 1
    _console.print(f"[dim]X: {len(posts)} posts para {query!r} ({kind})[/dim]")
    return SearchResult(
        posts=posts, actions=actions, daily_remaining=limiter.daily_remaining()
    )
