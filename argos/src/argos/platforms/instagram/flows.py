"""Flujos de lectura de Instagram: perfil, posts, hashtags, reels, búsqueda y comentarios.

Diseño deliberadamente conservador (prioridad del operador: no ser bloqueados):
  - DOM-first: se navega como un humano y se lee lo que la UI muestra.
  - Cada navegación/scroll/consulta pide turno al ``RateLimiter`` (token bucket +
    cuota diaria persistida) y espera pausas con jitter vía ``Pacer``.
  - Topes duros por corrida: ``MAX_POSTS_LIMIT`` posts, ``MAX_GRID_SCROLLS``
    scrolls de grilla y ``MAX_COMMENT_SCROLLS`` scrolls de comentarios.
  - Cualquier señal de checkpoint/rate-limit corta el flujo con evidencia
    (``BrowserSession.raise_if_problem``); nunca se reintenta a lo bruto.
"""

from __future__ import annotations

import re
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime
from urllib.parse import quote

from playwright.sync_api import Error as PlaywrightError
from rich.console import Console

from argos.browser.limiter import RateLimiter
from argos.browser.pacing import Pacer
from argos.browser.session import BrowserSession
from argos.errors import ExtractionError, UsageError
from argos.models import Comment, Post, Profile, SearchHit
from argos.platforms.instagram.extract import (
    is_private_page,
    is_unavailable_page,
    parse_comments,
    parse_grid,
    parse_post_page,
    parse_profile,
    parse_search_panel,
)
from argos.variants import name_variants, username_variants

_BASE = "https://www.instagram.com"
_USERNAME_RE = re.compile(r"^[A-Za-z0-9._]{1,40}$")
_TAG_RE = re.compile(r"^[\w.]{1,60}$", re.UNICODE)
_SHORTCODE_RE = re.compile(r"^[A-Za-z0-9_-]{5,30}$")

MAX_POSTS_LIMIT = 36
MAX_COMMENTS_LIMIT = 60
MAX_GRID_SCROLLS = 6
MAX_COMMENT_SCROLLS = 4
_GRID_WAIT_MS = 20_000
_REEL_WAIT_MS = 20_000

_console = Console(stderr=True)


# --------------------------------------------------------------------------- #
# Normalización
# --------------------------------------------------------------------------- #


def normalize_username(value: str) -> str:
    """Acepta ``@usuario``, ``usuario`` o la URL del perfil."""
    raw = value.strip()
    if "://" in raw or raw.lower().startswith("instagram.com"):
        raw = raw.rstrip("/").split("/")[-1]
    handle = raw.lstrip("@").strip()
    if not _USERNAME_RE.match(handle):
        raise UsageError(
            f"username inválido: {value!r}",
            hint="acepta @usuario, usuario o la URL del perfil",
        )
    return handle


def normalize_hashtag(value: str) -> str:
    """Acepta ``#tag``, ``tag`` o la URL de explore/tags."""
    raw = value.strip()
    if "://" in raw or raw.lower().startswith("instagram.com"):
        raw = raw.rstrip("/").split("/")[-1]
    tag = raw.lstrip("#").strip()
    if not _TAG_RE.match(tag):
        raise UsageError(
            f"hashtag inválido: {value!r}",
            hint="acepta #etiqueta o la etiqueta sola (letras, números, guión bajo)",
        )
    return tag


def normalize_post_url(value: str) -> str:
    """Acepta la URL del post o directamente el shortcode."""
    raw = value.strip()
    if raw.startswith("http"):
        if "instagram.com" not in raw or not re.search(r"/(?:p|reel)/", raw):
            raise UsageError(
                f"URL de post inválida: {value!r}",
                hint="se espera algo como https://www.instagram.com/usuario/p/SHORTCODE/",
            )
        return raw.rstrip("/") + "/"
    code = raw.strip("/").split("/")[-1]
    if not _SHORTCODE_RE.match(code):
        raise UsageError(
            f"shortcode inválido: {value!r}",
            hint="pasá la URL del post o el shortcode (p. ej. Ddr-AMmDxqn)",
        )
    return f"{_BASE}/p/{code}/"


def parse_since(value: str) -> datetime:
    """``--since`` en ISO 8601 (fecha sola o completa); naive = UTC."""
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        raise UsageError(
            f"fecha inválida para --since: {value!r}",
            hint="usá ISO 8601, por ejemplo 2026-09-01",
        ) from None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


# --------------------------------------------------------------------------- #
# Resultados
# --------------------------------------------------------------------------- #


@dataclass
class ProfileResult:
    profile: Profile
    recent_posts: list[Post] = field(default_factory=list)
    actions: int = 0
    daily_remaining: int = 0
    note: str | None = None


@dataclass
class PostsResult:
    posts: list[Post] = field(default_factory=list)
    actions: int = 0
    daily_remaining: int = 0
    stopped_at_since: bool = False
    note: str | None = None


@dataclass
class SearchResult:
    posts: list[Post] = field(default_factory=list)
    hits: list[SearchHit] = field(default_factory=list)
    actions: int = 0
    daily_remaining: int = 0
    note: str | None = None


@dataclass
class CommentsResult:
    comments: list[Comment] = field(default_factory=list)
    actions: int = 0
    daily_remaining: int = 0
    note: str | None = None


# --------------------------------------------------------------------------- #
# Helpers internos
# --------------------------------------------------------------------------- #


def _clamp(limit: int, maximum: int) -> int:
    return max(1, min(limit, maximum))


def _open(
    session: BrowserSession,
    url: str,
    *,
    wait_selector: str | None = None,
    wait_ms: int = _GRID_WAIT_MS,
    unavailable_message: str = "la página no existe o no está disponible",
) -> None:
    """Navega, valida la página y espera (acotado) al contenido esperado."""
    session.goto(url)
    session.raise_if_problem()
    if is_unavailable_page(session.page):
        raise ExtractionError(unavailable_message)
    if wait_selector:
        with suppress(PlaywrightError):
            session.page.wait_for_selector(wait_selector, timeout=wait_ms)


def _collect_grid(
    session: BrowserSession,
    *,
    author: str | None,
    limit: int,
    limiter: RateLimiter,
    pacer: Pacer,
    actions: int,
) -> tuple[list[Post], int]:
    """Lee la grilla y scrollea (con tope) hasta juntar ``limit`` posts."""
    posts = parse_grid(session.page, limit=limit, author=author)
    scrolls = 0
    while len(posts) < limit and scrolls < MAX_GRID_SCROLLS:
        before = len(posts)
        limiter.before_action()
        actions += 1
        pacer.scroll(session.page, steps=2)
        posts = parse_grid(session.page, limit=limit, author=author)
        scrolls += 1
        if len(posts) <= before:  # no hay más contenido
            break
    return posts, actions


def _visit_posts(
    session: BrowserSession,
    briefs: list[Post],
    *,
    author: str | None,
    limiter: RateLimiter,
    pacer: Pacer,
    actions: int,
    since: datetime | None,
) -> tuple[list[Post], int, bool]:
    """Visita cada post para leer métricas y fecha; corta con ``since``."""
    posts: list[Post] = []
    stopped = False
    total = len(briefs)
    for index, brief in enumerate(briefs, 1):
        pacer.dwell()
        limiter.before_action()
        actions += 1
        session.goto(brief.url)
        session.raise_if_problem()
        post = parse_post_page(session.page, url=brief.url, author=author or brief.author)
        post.caption = post.caption or brief.caption
        post.thumbnail_url = post.thumbnail_url or brief.thumbnail_url
        post.views = post.views or brief.views
        if since is not None and post.created_at is not None and post.created_at < since:
            stopped = True
            break
        posts.append(post)
        _console.print(f"[dim]  post {index}/{total} leído[/dim]")
    return posts, actions, stopped


# --------------------------------------------------------------------------- #
# Flujos
# --------------------------------------------------------------------------- #


def fetch_profile(
    session: BrowserSession,
    username: str,
    *,
    limiter: RateLimiter,
    pacer: Pacer,
    limit: int = 12,
) -> ProfileResult:
    """Perfil + posts visibles en la grilla (sin visitar cada post)."""
    handle = normalize_username(username)
    limit = _clamp(limit, MAX_POSTS_LIMIT)

    actions = 0
    limiter.before_action()
    actions += 1
    _open(
        session,
        f"{_BASE}/{handle}/",
        unavailable_message=f"la cuenta @{handle} no existe o no está disponible",
    )
    pacer.dwell()

    profile = parse_profile(session.page, handle)
    posts, actions = _collect_grid(
        session, author=handle, limit=limit, limiter=limiter, pacer=pacer, actions=actions
    )

    note = None
    if not posts and profile.is_private:
        note = f"@{handle} es una cuenta privada: no hay posts visibles"
    _console.print(
        f"[dim]@{handle}: perfil leído, {len(posts)} posts en grilla "
        f"({actions} acciones)[/dim]"
    )
    return ProfileResult(
        profile=profile,
        recent_posts=posts,
        actions=actions,
        daily_remaining=limiter.daily_remaining(),
        note=note,
    )


def fetch_posts(
    session: BrowserSession,
    username: str,
    *,
    limiter: RateLimiter,
    pacer: Pacer,
    limit: int = 12,
    details: bool = True,
    since: datetime | None = None,
) -> PostsResult:
    """Posts del perfil; con ``details`` visita cada post (likes/comentarios/fecha)."""
    handle = normalize_username(username)
    limit = _clamp(limit, MAX_POSTS_LIMIT)

    actions = 0
    limiter.before_action()
    actions += 1
    _open(
        session,
        f"{_BASE}/{handle}/",
        unavailable_message=f"la cuenta @{handle} no existe o no está disponible",
    )
    pacer.dwell()
    briefs, actions = _collect_grid(
        session, author=handle, limit=limit, limiter=limiter, pacer=pacer, actions=actions
    )

    if not briefs:
        note = (
            f"@{handle} es una cuenta privada: no hay posts visibles"
            if is_private_page(session.page)
            else f"@{handle} no muestra posts (¿cuenta vacía?)"
        )
        return PostsResult(
            actions=actions, daily_remaining=limiter.daily_remaining(), note=note
        )

    if not details:
        return PostsResult(
            posts=briefs[:limit],
            actions=actions,
            daily_remaining=limiter.daily_remaining(),
        )

    posts, actions, stopped = _visit_posts(
        session,
        briefs[:limit],
        author=handle,
        limiter=limiter,
        pacer=pacer,
        actions=actions,
        since=since,
    )
    return PostsResult(
        posts=posts,
        actions=actions,
        daily_remaining=limiter.daily_remaining(),
        stopped_at_since=stopped,
    )


def fetch_hashtag(
    session: BrowserSession,
    tag: str,
    *,
    limiter: RateLimiter,
    pacer: Pacer,
    limit: int = 12,
    details: bool = False,
    since: datetime | None = None,
) -> PostsResult:
    """Posts de un hashtag (la página de tags redirige al buscador por keyword)."""
    handle = normalize_hashtag(tag)
    limit = _clamp(limit, MAX_POSTS_LIMIT)

    actions = 0
    limiter.before_action()
    actions += 1
    _open(
        session,
        f"{_BASE}/explore/tags/{handle}/",
        unavailable_message=f"el hashtag #{handle} no está disponible",
    )
    pacer.dwell()
    briefs, actions = _collect_grid(
        session, author=None, limit=limit, limiter=limiter, pacer=pacer, actions=actions
    )

    if not briefs:
        return PostsResult(
            actions=actions,
            daily_remaining=limiter.daily_remaining(),
            note=f"#{handle} no muestra posts",
        )
    if not details:
        return PostsResult(
            posts=briefs[:limit],
            actions=actions,
            daily_remaining=limiter.daily_remaining(),
        )

    posts, actions, stopped = _visit_posts(
        session,
        briefs[:limit],
        author=None,
        limiter=limiter,
        pacer=pacer,
        actions=actions,
        since=since,
    )
    return PostsResult(
        posts=posts,
        actions=actions,
        daily_remaining=limiter.daily_remaining(),
        stopped_at_since=stopped,
    )


def fetch_reels(
    session: BrowserSession,
    username: str,
    *,
    limiter: RateLimiter,
    pacer: Pacer,
    limit: int = 12,
    details: bool = False,
    since: datetime | None = None,
) -> PostsResult:
    """Reels de un perfil (pestaña /reels/); con ``details`` visita cada reel."""
    handle = normalize_username(username)
    limit = _clamp(limit, MAX_POSTS_LIMIT)

    actions = 0
    limiter.before_action()
    actions += 1
    _open(
        session,
        f"{_BASE}/{handle}/reels/",
        wait_selector="a[href*='/reel/']",
        wait_ms=_REEL_WAIT_MS,
        unavailable_message=f"la cuenta @{handle} no existe o no está disponible",
    )
    pacer.dwell()
    briefs, actions = _collect_grid(
        session, author=handle, limit=limit, limiter=limiter, pacer=pacer, actions=actions
    )

    if not briefs:
        return PostsResult(
            actions=actions,
            daily_remaining=limiter.daily_remaining(),
            note=f"@{handle} no muestra reels",
        )
    if not details:
        return PostsResult(
            posts=briefs[:limit],
            actions=actions,
            daily_remaining=limiter.daily_remaining(),
        )

    posts, actions, stopped = _visit_posts(
        session,
        briefs[:limit],
        author=handle,
        limiter=limiter,
        pacer=pacer,
        actions=actions,
        since=since,
    )
    return PostsResult(
        posts=posts,
        actions=actions,
        daily_remaining=limiter.daily_remaining(),
        stopped_at_since=stopped,
    )


def _search_posts_once(
    session: BrowserSession,
    query: str,
    *,
    limiter: RateLimiter,
    pacer: Pacer,
    limit: int,
) -> SearchResult:
    actions = 0
    limiter.before_action()
    actions += 1
    _open(
        session,
        f"{_BASE}/explore/search/keyword/?q={quote(query)}",
        unavailable_message="la búsqueda no está disponible",
    )
    pacer.dwell()
    briefs, actions = _collect_grid(
        session, author=None, limit=limit, limiter=limiter, pacer=pacer, actions=actions
    )
    note = None if briefs else f"la búsqueda «{query}» no devolvió posts"
    return SearchResult(
        posts=briefs[:limit],
        actions=actions,
        daily_remaining=limiter.daily_remaining(),
        note=note,
    )


def _typeahead(
    session: BrowserSession,
    queries: list[str],
    *,
    limiter: RateLimiter,
    pacer: Pacer,
    limit: int,
) -> SearchResult:
    """Abre el panel una vez y tipea cada consulta (más humano y más barato)."""
    actions = 0
    limiter.before_action()
    actions += 1
    _open(session, f"{_BASE}/")
    page = session.page

    opened = False
    for selector in (
        "svg[aria-label='Search']",
        "svg[aria-label='Buscar']",
        "a[href='/explore/search/']",
    ):
        locator = page.locator(selector)
        if locator.count() == 0:
            continue
        try:
            locator.first.click(timeout=5000)
            opened = True
            break
        except PlaywrightError:
            continue
    if not opened:
        raise ExtractionError("no se pudo abrir el panel de búsqueda de Instagram")

    page.wait_for_timeout(800)
    search_input = page.locator(
        "input[aria-label='Search input'], input[aria-label*='uscar'], input[type='text']"
    ).first
    if search_input.count() == 0:
        raise ExtractionError("no se encontró el campo de búsqueda")

    merged: dict[str, SearchHit] = {}
    for query in queries:
        search_input.fill("")
        search_input.focus()
        pacer.short()
        search_input.press_sequentially(query, delay=90)
        limiter.before_action()
        actions += 1  # la consulta del typeahead dispara requests

        hits: list[SearchHit] = []
        for _ in range(3):
            page.wait_for_timeout(1200)
            hits = parse_search_panel(page, limit)
            if hits:
                break
        for hit in hits:
            merged.setdefault(hit.url, hit)
        if len(merged) >= limit:
            break

    final = list(merged.values())[:limit]
    if not final:
        raise ExtractionError(
            "la búsqueda de usuarios no devolvió resultados "
            "(¿sesión vencida o panel no renderizado?)"
        )
    return SearchResult(
        hits=final, actions=actions, daily_remaining=limiter.daily_remaining()
    )


def search(
    session: BrowserSession,
    query: str,
    *,
    limiter: RateLimiter,
    pacer: Pacer,
    kind: str = "posts",
    limit: int = 12,
    variants: bool = False,
) -> SearchResult:
    """Búsqueda en Instagram.

    - ``kind='posts'``: grid por keyword; con ``variants`` prueba variantes del
      nombre (con espacios) y junta resultados.
    - ``kind='users'``: panel typeahead; con ``variants`` prueba variantes de
      *username* (junto, con punto, guion bajo) sin re-abrir el panel.
    """
    cleaned = query.strip().lstrip("#")
    if not cleaned:
        raise UsageError("búsqueda vacía", hint="pasá una palabra o hashtag")
    limit = _clamp(limit, MAX_POSTS_LIMIT)

    if kind == "posts":
        queries = name_variants(cleaned) if variants else [cleaned]
        merged: dict[str, Post] = {}
        actions = 0
        remaining = limiter.daily_remaining()
        for item in queries:
            result = _search_posts_once(session, item, limiter=limiter, pacer=pacer, limit=limit)
            actions += result.actions
            remaining = result.daily_remaining
            for post in result.posts:
                merged.setdefault(post.url, post)
            if len(merged) >= limit:
                break
        posts = list(merged.values())[:limit]
        note = None if posts else f"la búsqueda «{cleaned}» no devolvió posts"
        return SearchResult(posts=posts, actions=actions, daily_remaining=remaining, note=note)

    if kind != "users":
        raise UsageError(
            f"tipo de búsqueda inválido: {kind!r}", hint="opciones: posts, users"
        )

    queries = username_variants(cleaned) if variants else [cleaned]
    return _typeahead(session, queries, limiter=limiter, pacer=pacer, limit=limit)


def fetch_comments(
    session: BrowserSession,
    post: str,
    *,
    limiter: RateLimiter,
    pacer: Pacer,
    limit: int = 20,
) -> CommentsResult:
    """Comentarios visibles de un post (scroll acotado para cargar más)."""
    url = normalize_post_url(post)
    limit = _clamp(limit, MAX_COMMENTS_LIMIT)

    actions = 0
    limiter.before_action()
    actions += 1
    _open(
        session,
        url,
        unavailable_message="el post no existe o no está disponible",
    )
    pacer.dwell()

    comments = parse_comments(session.page, post_url=url, limit=limit)
    scrolls = 0
    while len(comments) < limit and scrolls < MAX_COMMENT_SCROLLS:
        before = len(comments)
        limiter.before_action()
        actions += 1
        pacer.scroll(session.page, steps=2)
        merged = {comment.id: comment for comment in comments}
        for comment in parse_comments(session.page, post_url=url, limit=limit):
            merged.setdefault(comment.id, comment)
        comments = list(merged.values())[:limit]
        scrolls += 1
        if len(comments) <= before:
            break

    note = None
    if not comments:
        note = "no se encontraron comentarios visibles en el post"
    return CommentsResult(
        comments=comments,
        actions=actions,
        daily_remaining=limiter.daily_remaining(),
        note=note,
    )
