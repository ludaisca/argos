"""Flujos de LinkedIn: perfil/empresa y búsqueda. Requiere sesión del humano."""

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
from argos.models import Post, Profile, SearchHit
from argos.platforms.linkedin.extract import (
    is_login_wall,
    parse_posts,
    parse_profile,
    parse_search_results,
)

_BASE = "https://www.linkedin.com"
MAX_LIMIT = 30
_WAIT_MS = 12000
_console = Console(stderr=True)
_LOGIN_HINT = "ejecutá `argos login linkedin` e iniciá sesión en la ventana"


@dataclass
class ProfileResult:
    profile: Profile | None = None
    recent_posts: list[Post] = field(default_factory=list)
    actions: int = 0
    daily_remaining: int = 0
    note: str | None = None


@dataclass
class SearchResult:
    hits: list[SearchHit] = field(default_factory=list)
    posts: list[Post] = field(default_factory=list)
    actions: int = 0
    daily_remaining: int = 0
    note: str | None = None


def normalize_target(value: str) -> tuple[str, str]:
    """→ ``(kind, slug)`` donde kind es ``person`` o ``company``."""
    text = value.strip()
    if text.startswith("http"):
        if "/company/" in text:
            return "company", text.split("/company/", 1)[1].split("/")[0].split("?")[0]
        if "/in/" in text:
            return "person", text.split("/in/", 1)[1].split("/")[0].split("?")[0]
        raise UsageError(f"no reconozco el perfil de LinkedIn en {value!r}")
    if text.startswith("company:") or text.startswith("empresa:"):
        return "company", text.split(":", 1)[1].strip().strip("/")
    if text.startswith("person:") or text.startswith("persona:"):
        return "person", text.split(":", 1)[1].strip().strip("/")
    return "person", text.strip("/")


def _open(session: BrowserSession, url: str) -> None:
    session.goto(url)
    session.raise_if_problem()
    if is_login_wall(session.page):
        raise LoginRequiredError(
            "LinkedIn pidió login para esta página", hint=_LOGIN_HINT
        )
    with contextlib.suppress(PlaywrightError):
        session.page.wait_for_timeout(1200)


def fetch_profile(
    session: BrowserSession,
    value: str,
    *,
    limiter: RateLimiter,
    pacer: Pacer,
    limit: int = 12,
) -> ProfileResult:
    """Perfil/empresa + publicaciones recientes."""
    limit = max(1, min(limit, MAX_LIMIT))
    kind, slug = normalize_target(value)
    if not slug:
        raise UsageError("falta el perfil de LinkedIn (slug o URL)")
    actions = 0
    limiter.before_action()
    actions += 1
    path = "company" if kind == "company" else "in"
    _open(session, f"{_BASE}/{path}/{slug}/")
    pacer.dwell()
    profile = parse_profile(session.page)

    posts: list[Post] = []
    if limit > 0:
        posts_url = (
            f"{_BASE}/company/{slug}/posts/?feedView=all"
            if kind == "company"
            else f"{_BASE}/in/{slug}/recent-activity/all/"
        )
        limiter.before_action()
        actions += 1
        _open(session, posts_url)
        pacer.dwell()
        posts = parse_posts(session.page, limit=limit)
        scrolls = 0
        while len(posts) < limit and scrolls < 4:
            limiter.before_action()
            actions += 1
            pacer.scroll(session.page, steps=2)
            posts = parse_posts(session.page, limit=limit)
            scrolls += 1

    _console.print(
        f"[dim]LinkedIn {kind}/{slug}: perfil + {len(posts)} posts ({actions} acciones)[/dim]"
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
    kind: str = "people",
    limit: int = 10,
) -> SearchResult:
    """Búsqueda de personas, empresas o contenido."""
    limit = max(1, min(limit, MAX_LIMIT))
    routes = {
        "people": "people",
        "personas": "people",
        "companies": "companies",
        "empresas": "companies",
        "posts": "content",
        "contenido": "content",
    }
    route = routes.get(kind)
    if route is None:
        raise UsageError(
            f"kind desconocido: {kind!r}", hint="opciones: people, companies, posts"
        )
    actions = 0
    limiter.before_action()
    actions += 1
    _open(session, f"{_BASE}/search/results/{route}/?keywords={quote_plus(query)}")
    pacer.dwell()
    if route == "content":
        posts = parse_posts(session.page, limit=limit)
        scrolls = 0
        while len(posts) < limit and scrolls < 4:
            limiter.before_action()
            actions += 1
            pacer.scroll(session.page, steps=2)
            posts = parse_posts(session.page, limit=limit)
            scrolls += 1
        _console.print(f"[dim]LinkedIn: {len(posts)} posts para {query!r}[/dim]")
        return SearchResult(
            posts=posts, actions=actions, daily_remaining=limiter.daily_remaining()
        )
    hits = parse_search_results(
        session.page, kind="companies" if route == "companies" else "people", limit=limit
    )
    _console.print(f"[dim]LinkedIn: {len(hits)} resultados para {query!r}[/dim]")
    return SearchResult(
        hits=hits, actions=actions, daily_remaining=limiter.daily_remaining()
    )
