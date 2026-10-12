"""Flujos de YouTube: búsqueda, canal y video (público: no requiere login)."""

from __future__ import annotations

import contextlib
from dataclasses import dataclass, field
from urllib.parse import quote_plus

from playwright.sync_api import Error as PlaywrightError
from rich.console import Console

from argos.browser.limiter import RateLimiter
from argos.browser.pacing import Pacer
from argos.browser.session import BrowserSession
from argos.errors import ExtractionError, UsageError
from argos.models import Comment, Post, Profile, SearchHit
from argos.platforms.youtube.extract import (
    initial_data,
    parse_channel_meta,
    parse_channel_videos,
    parse_comments,
    parse_search_channels,
    parse_search_videos,
    parse_video_meta,
    video_id_from,
)

_BASE = "https://www.youtube.com"
MAX_LIMIT = 40
_WAIT_MS = 15000
_console = Console(stderr=True)


@dataclass
class SearchResult:
    posts: list[Post] = field(default_factory=list)
    hits: list[SearchHit] = field(default_factory=list)
    actions: int = 0
    daily_remaining: int = 0
    note: str | None = None


@dataclass
class ChannelResult:
    profile: Profile | None = None
    recent_posts: list[Post] = field(default_factory=list)
    actions: int = 0
    daily_remaining: int = 0
    note: str | None = None


@dataclass
class VideoResult:
    post: Post | None = None
    comments: list[Comment] = field(default_factory=list)
    actions: int = 0
    daily_remaining: int = 0
    note: str | None = None


def normalize_channel(value: str) -> str:
    """@handle, handle, URL de canal o channel/UC… → slug limpio."""
    text = value.strip()
    if text.startswith("http"):
        text = text.split("youtube.com/", 1)[-1].split("?", 1)[0].strip("/")
    if text.startswith("channel/"):
        text = text[len("channel/") :]
    return text.lstrip("@")


def _open(session: BrowserSession, url: str, *, wait_ms: int = _WAIT_MS) -> None:
    session.goto(url)
    session.raise_if_problem()
    with contextlib.suppress(PlaywrightError):
        session.page.wait_for_selector("ytd-app", timeout=wait_ms)


def search(
    session: BrowserSession,
    query: str,
    *,
    limiter: RateLimiter,
    pacer: Pacer,
    kind: str = "videos",
    limit: int = 12,
) -> SearchResult:
    """Busca videos o canales. ``kind``: ``videos`` (default) o ``channels``."""
    limit = max(1, min(limit, MAX_LIMIT))
    actions = 0
    limiter.before_action()
    actions += 1
    _open(session, f"{_BASE}/results?search_query={quote_plus(query)}")
    pacer.dwell()
    data = initial_data(session.page)
    if not isinstance(data, dict):
        raise ExtractionError(
            "YouTube no devolvió ytInitialData",
            hint="puede ser un layout nuevo o un bloqueo temporal",
        )
    if kind == "channels":
        hits = parse_search_channels(data, limit=limit)
        _console.print(f"[dim]YouTube: {len(hits)} canales para {query!r}[/dim]")
        return SearchResult(
            hits=hits, actions=actions, daily_remaining=limiter.daily_remaining()
        )
    posts = parse_search_videos(data, limit=limit)
    _console.print(f"[dim]YouTube: {len(posts)} videos para {query!r}[/dim]")
    return SearchResult(
        posts=posts, actions=actions, daily_remaining=limiter.daily_remaining()
    )


def fetch_channel(
    session: BrowserSession,
    handle: str,
    *,
    limiter: RateLimiter,
    pacer: Pacer,
    limit: int = 12,
) -> ChannelResult:
    """Canal (perfil + últimos videos)."""
    limit = max(1, min(limit, MAX_LIMIT))
    slug = normalize_channel(handle)
    if not slug:
        raise UsageError("falta el handle o URL del canal de YouTube")
    base = f"{_BASE}/channel/{slug}" if slug.startswith("UC") else f"{_BASE}/@{slug}"
    actions = 0
    limiter.before_action()
    actions += 1
    _open(session, f"{base}/videos")
    pacer.dwell()
    data = initial_data(session.page)
    if not isinstance(data, dict):
        raise ExtractionError("YouTube no devolvió ytInitialData")
    profile = parse_channel_meta(data, slug)
    posts = parse_channel_videos(data, limit=limit, author=slug)
    _console.print(
        f"[dim]YouTube @{slug}: perfil + {len(posts)} videos ({actions} acciones)[/dim]"
    )
    return ChannelResult(
        profile=profile,
        recent_posts=posts,
        actions=actions,
        daily_remaining=limiter.daily_remaining(),
    )


def fetch_video(
    session: BrowserSession,
    value: str,
    *,
    limiter: RateLimiter,
    pacer: Pacer,
    limit: int = 15,
    comments: bool = True,
) -> VideoResult:
    """Video (metadatos) y, por defecto, comentarios visibles tras scroll."""
    video_id = video_id_from(value)
    if not video_id:
        raise UsageError(f"no pude reconocer un video en {value!r}")
    actions = 0
    limiter.before_action()
    actions += 1
    url = f"{_BASE}/watch?v={video_id}"
    _open(session, url)
    pacer.dwell()
    data = initial_data(session.page) or {}
    post = parse_video_meta(data, video_id)
    found: list[Comment] = []
    if comments and limit > 0:
        for _ in range(3):
            limiter.before_action()
            actions += 1
            pacer.scroll(session.page, steps=3)
        found = parse_comments(session.page, limit=limit, post_url=post.url)
    _console.print(
        f"[dim]YouTube video {video_id}: {len(found)} comentarios ({actions} acciones)[/dim]"
    )
    return VideoResult(
        post=post,
        comments=found,
        actions=actions,
        daily_remaining=limiter.daily_remaining(),
    )
