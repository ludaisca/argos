"""Flujos de lectura de Facebook: páginas, búsqueda y feed de grupos.

Mismas reglas de movimiento cuidadoso que Instagram: DOM-first, cada acción de
red pasa por el ``RateLimiter`` (8/min, 400/día para Facebook) y el ``Pacer``,
con topes por corrida y parada inmediata ante cualquier señal de bloqueo.
"""

from __future__ import annotations

import re
from contextlib import suppress
from dataclasses import dataclass, field
from urllib.parse import quote

from playwright.sync_api import Error as PlaywrightError
from rich.console import Console

from argos.browser.limiter import RateLimiter
from argos.browser.pacing import Pacer
from argos.browser.session import BrowserSession
from argos.errors import ExtractionError, UsageError
from argos.models import Post, Profile, SearchHit
from argos.platforms.facebook.extract import (
    parse_posts,
    parse_profile,
    parse_search_results,
)
from argos.variants import name_variants

_BASE = "https://www.facebook.com"
_SLUG_RE = re.compile(r"^[\w.\-]{1,80}$", re.UNICODE)

MAX_POSTS_LIMIT = 36
MAX_SCROLLS = 4
_RENDER_WAIT_MS = 8_000
_SETTLE_MS = 1_200
_SEARCH_KINDS = ("pages", "groups", "people")

_console = Console(stderr=True)


def normalize_page(value: str) -> str:
    """Acepta ``slug``, ``@slug`` o la URL de la página."""
    raw = value.strip()
    if "://" in raw or raw.lower().startswith("facebook.com"):
        raw = raw.split("?")[0].rstrip("/").split("/")[-1]
    slug = raw.lstrip("@").strip()
    if not _SLUG_RE.match(slug):
        raise UsageError(
            f"página inválida: {value!r}",
            hint="acepta el slug (NASA) o la URL de la página",
        )
    return slug


@dataclass
class PageResult:
    profile: Profile
    posts: list[Post] = field(default_factory=list)
    actions: int = 0
    daily_remaining: int = 0
    note: str | None = None


@dataclass
class PostsResult:
    posts: list[Post] = field(default_factory=list)
    actions: int = 0
    daily_remaining: int = 0
    note: str | None = None


@dataclass
class SearchResult:
    hits: list[SearchHit] = field(default_factory=list)
    actions: int = 0
    daily_remaining: int = 0
    note: str | None = None


def _clamp(limit: int) -> int:
    return max(1, min(limit, MAX_POSTS_LIMIT))


def _open(session: BrowserSession, url: str, *, wait_ms: int | None = None) -> None:
    session.goto(url)
    session.raise_if_problem()
    # Facebook renderiza por capas: damos un margen acotado a que hidrate.
    with suppress(PlaywrightError):
        session.page.wait_for_selector(
            "div[role=article]", timeout=_RENDER_WAIT_MS if wait_ms is None else wait_ms
        )
    session.page.wait_for_timeout(_SETTLE_MS)


def _collect_posts(
    session: BrowserSession,
    *,
    limit: int,
    limiter: RateLimiter,
    pacer: Pacer,
    actions: int,
    author_hint: str | None,
    page_url: str,
) -> tuple[list[Post], int]:
    posts = parse_posts(
        session.page, limit=limit, author_hint=author_hint, page_url=page_url
    )
    scrolls = 0
    while len(posts) < limit and scrolls < MAX_SCROLLS:
        before = len(posts)
        limiter.before_action()
        actions += 1
        pacer.scroll(session.page, steps=2)
        session.page.wait_for_timeout(1200)
        posts = parse_posts(
            session.page, limit=limit, author_hint=author_hint, page_url=page_url
        )
        scrolls += 1
        if len(posts) <= before:
            break
    return posts, actions


def fetch_page(
    session: BrowserSession,
    value: str,
    *,
    limiter: RateLimiter,
    pacer: Pacer,
    limit: int = 12,
) -> PageResult:
    """Página de Facebook: info del header + posts visibles (con scroll acotado)."""
    slug = normalize_page(value)
    limit = _clamp(limit)
    url = f"{_BASE}/{slug}/"

    actions = 0
    limiter.before_action()
    actions += 1
    _open(session, url)
    pacer.dwell()

    profile = parse_profile(session.page, slug)
    posts, actions = _collect_posts(
        session,
        limit=limit,
        limiter=limiter,
        pacer=pacer,
        actions=actions,
        author_hint=profile.full_name,
        page_url=url,
    )
    note = None
    if not posts:
        note = f"la página @{slug} no muestra posts nuevos (o el feed no cargó)"
    _console.print(
        f"[dim]@{slug}: {len(posts)} posts leídos ({actions} acciones)[/dim]"
    )
    return PageResult(
        profile=profile,
        posts=posts,
        actions=actions,
        daily_remaining=limiter.daily_remaining(),
        note=note,
    )


def fetch_group_feed(
    session: BrowserSession,
    *,
    limiter: RateLimiter,
    pacer: Pacer,
    limit: int = 12,
) -> PostsResult:
    """Posts del feed de tus grupos (/groups/feed/)."""
    limit = _clamp(limit)
    url = f"{_BASE}/groups/feed/"

    actions = 0
    limiter.before_action()
    actions += 1
    _open(session, url)
    pacer.dwell()

    posts, actions = _collect_posts(
        session,
        limit=limit,
        limiter=limiter,
        pacer=pacer,
        actions=actions,
        author_hint=None,
        page_url=url,
    )
    note = None
    if not posts:
        note = "sin novedades en tus grupos (o no sos miembro de ningún grupo activo)"
    return PostsResult(
        posts=posts,
        actions=actions,
        daily_remaining=limiter.daily_remaining(),
        note=note,
    )


def _search_once(
    session: BrowserSession,
    query: str,
    *,
    limiter: RateLimiter,
    pacer: Pacer,
    kind: str,
    limit: int,
) -> SearchResult:
    """Una consulta de búsqueda; devuelve ``hits=[]`` si no hay resultados."""
    url = f"{_BASE}/search/{kind}/?q={quote(query)}"
    actions = 0
    limiter.before_action()
    actions += 1
    _open(session, url)
    pacer.dwell()

    hits = parse_search_results(session.page, kind=kind, limit=limit)
    scrolls = 0
    while len(hits) < limit and scrolls < MAX_SCROLLS:
        before = len(hits)
        limiter.before_action()
        actions += 1
        pacer.scroll(session.page, steps=2)
        session.page.wait_for_timeout(1200)
        hits = parse_search_results(session.page, kind=kind, limit=limit)
        scrolls += 1
        if len(hits) <= before:
            break
    return SearchResult(
        hits=hits,
        actions=actions,
        daily_remaining=limiter.daily_remaining(),
    )


def search(
    session: BrowserSession,
    query: str,
    *,
    limiter: RateLimiter,
    pacer: Pacer,
    kind: str = "pages",
    limit: int = 12,
    variants: bool = False,
) -> SearchResult:
    """Busca páginas, grupos o personas (``/search/{kind}/?q=...``).

    Con ``variants=True`` prueba variantes del nombre (quitar apellido, invertir
    orden) y junta los resultados sin duplicados por URL.
    """
    cleaned = query.strip()
    if not cleaned:
        raise UsageError("búsqueda vacía", hint="pasá una palabra o nombre")
    if kind not in _SEARCH_KINDS:
        raise UsageError(
            f"tipo de búsqueda inválido: {kind!r}",
            hint=f"opciones: {', '.join(_SEARCH_KINDS)}",
        )
    limit = _clamp(limit)

    queries = name_variants(cleaned) if variants else [cleaned]
    merged: dict[str, SearchHit] = {}
    actions = 0
    remaining = limiter.daily_remaining()
    for item in queries:
        result = _search_once(
            session, item, limiter=limiter, pacer=pacer, kind=kind, limit=limit
        )
        actions += result.actions
        remaining = result.daily_remaining
        for hit in result.hits:
            merged.setdefault(hit.url, hit)
        if len(merged) >= limit:
            break

    hits = list(merged.values())[:limit]
    if not hits:
        raise ExtractionError(
            f"la búsqueda de {kind} no devolvió resultados "
            "(¿sesión vencida o página sin resultados?)"
        )
    return SearchResult(hits=hits, actions=actions, daily_remaining=remaining)
