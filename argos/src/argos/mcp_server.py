"""Servidor MCP (stdio) que expone las lecturas de Argos como tools tipadas.

Pensado para n8n (nodo MCP Client) y para hosts de agentes con soporte MCP
(Claude Code, OpenCode, etc.). Todas las tools corren en modo headless y con
los mismos límites/pacing que la CLI: no se saltean la cuota ni las pausas.
"""

from __future__ import annotations

import asyncio
from typing import Any

from argos.browser.limiter import RateLimiter
from argos.browser.pacing import Pacer
from argos.browser.session import BrowserSession
from argos.config import ArgosConfig
from argos.doctor import collect
from argos.quota import quota_report


def _run(platform: str, flow: Any, *args: Any, **kwargs: Any) -> Any:
    """Ejecuta un flujo con su sesión, límites y pacing correspondientes."""
    config = ArgosConfig.load()
    limiter = RateLimiter(config, platform)
    pacer = Pacer()
    with BrowserSession(platform, config, headless=True) as session:
        return flow(session, *args, limiter=limiter, pacer=pacer, **kwargs)


def _posts_payload(result: Any) -> dict[str, Any]:
    return {
        "posts": [post.model_dump(mode="json") for post in result.posts],
        "note": result.note,
        "stopped_at_since": getattr(result, "stopped_at_since", None),
        "actions": result.actions,
        "daily_remaining": result.daily_remaining,
    }


def _profile_payload(result: Any) -> dict[str, Any]:
    return {
        "profile": result.profile.model_dump(mode="json"),
        "recent_posts": [post.model_dump(mode="json") for post in result.recent_posts],
        "note": result.note,
        "actions": result.actions,
        "daily_remaining": result.daily_remaining,
    }


def _search_payload(result: Any) -> dict[str, Any]:
    return {
        "posts": [post.model_dump(mode="json") for post in result.posts],
        "hits": [hit.model_dump(mode="json") for hit in result.hits],
        "note": result.note,
        "actions": result.actions,
        "daily_remaining": result.daily_remaining,
    }


def _comments_payload(result: Any) -> dict[str, Any]:
    return {
        "comments": [comment.model_dump(mode="json") for comment in result.comments],
        "note": result.note,
        "actions": result.actions,
        "daily_remaining": result.daily_remaining,
    }


def _page_payload(result: Any) -> dict[str, Any]:
    return {
        "profile": result.profile.model_dump(mode="json"),
        "posts": [post.model_dump(mode="json") for post in result.posts],
        "note": result.note,
        "actions": result.actions,
        "daily_remaining": result.daily_remaining,
    }


# --------------------------------------------------------------------------- #
# Implementaciones síncronas (testeables sin correr el server)
# --------------------------------------------------------------------------- #


def doctor_tool() -> dict[str, Any]:
    return collect(ArgosConfig.load(), headless=True)


def quota_tool(platform: str | None = None) -> dict[str, Any]:
    return quota_report(platform=platform)


def ig_profile_tool(username: str, limit: int = 12) -> dict[str, Any]:
    from argos.platforms.instagram import fetch_profile

    return _profile_payload(_run("instagram", fetch_profile, username, limit=limit))


def ig_posts_tool(
    username: str,
    limit: int = 12,
    since: str | None = None,
    details: bool = True,
) -> dict[str, Any]:
    from argos.platforms.instagram import fetch_posts, parse_since

    since_value = parse_since(since) if since else None
    return _posts_payload(
        _run(
            "instagram",
            fetch_posts,
            username,
            limit=limit,
            details=details,
            since=since_value,
        )
    )


def ig_hashtag_tool(tag: str, limit: int = 12, details: bool = False) -> dict[str, Any]:
    from argos.platforms.instagram import fetch_hashtag

    return _posts_payload(_run("instagram", fetch_hashtag, tag, limit=limit, details=details))


def ig_reels_tool(username: str, limit: int = 12, details: bool = False) -> dict[str, Any]:
    from argos.platforms.instagram import fetch_reels

    return _posts_payload(_run("instagram", fetch_reels, username, limit=limit, details=details))


def ig_search_tool(
    query: str,
    kind: str = "posts",
    limit: int = 12,
    variants: bool = False,
) -> dict[str, Any]:
    from argos.platforms.instagram import search

    return _search_payload(
        _run("instagram", search, query, kind=kind, limit=limit, variants=variants)
    )


def ig_comments_tool(post: str, limit: int = 20) -> dict[str, Any]:
    from argos.platforms.instagram import fetch_comments

    return _comments_payload(_run("instagram", fetch_comments, post, limit=limit))


def fb_page_tool(page: str, limit: int = 12) -> dict[str, Any]:
    from argos.platforms.facebook import fetch_page

    return _page_payload(_run("facebook", fetch_page, page, limit=limit))


def fb_search_tool(
    query: str,
    kind: str = "pages",
    limit: int = 12,
    variants: bool = False,
) -> dict[str, Any]:
    from argos.platforms.facebook import search

    return _search_payload(
        _run("facebook", search, query, kind=kind, limit=limit, variants=variants)
    )


def fb_groups_feed_tool(limit: int = 12) -> dict[str, Any]:
    from argos.platforms.facebook import fetch_group_feed

    return _posts_payload(_run("facebook", fetch_group_feed, limit=limit))


# --------------------------------------------------------------------------- #
# Server
# --------------------------------------------------------------------------- #


def build_server() -> Any:
    """Construye el server FastMCP con todas las tools registradas."""
    try:
        from mcp.server.mcpserver import MCPServer
    except ImportError as exc:  # pragma: no cover - cubierto por el CLI
        raise SystemExit(
            "MCP v2 no instalado. Instalá con: pip install 'argos[mcp]'"
        ) from exc

    mcp = MCPServer(
        "argos",
        instructions=(
            "Herramientas de LECTURA de Instagram y Facebook con la sesión del "
            "operador. Solo contenido visible; no hay acciones de escritura. "
            "Chequeá `quota` antes y detenete ante errores de límite (no reintentes)."
        ),
    )

    @mcp.tool()
    async def doctor() -> dict[str, Any]:
        """Estado de las sesiones (instalado + login) por plataforma."""
        return await asyncio.to_thread(doctor_tool)

    @mcp.tool()
    async def quota(platform: str | None = None) -> dict[str, Any]:
        """Cuota diaria: acciones usadas/restantes por plataforma (sin navegador)."""
        return await asyncio.to_thread(quota_tool, platform)

    @mcp.tool()
    async def ig_profile(username: str, limit: int = 12) -> dict[str, Any]:
        """Perfil de Instagram (bio, métricas y posts de la grilla)."""
        return await asyncio.to_thread(ig_profile_tool, username, limit)

    @mcp.tool()
    async def ig_posts(
        username: str, limit: int = 12, since: str | None = None, details: bool = True
    ) -> dict[str, Any]:
        """Posts de un perfil de Instagram (con detalle: likes/comentarios/fecha)."""
        return await asyncio.to_thread(ig_posts_tool, username, limit, since, details)

    @mcp.tool()
    async def ig_hashtag(tag: str, limit: int = 12, details: bool = False) -> dict[str, Any]:
        """Posts de un hashtag de Instagram."""
        return await asyncio.to_thread(ig_hashtag_tool, tag, limit, details)

    @mcp.tool()
    async def ig_reels(username: str, limit: int = 12, details: bool = False) -> dict[str, Any]:
        """Reels de un perfil de Instagram."""
        return await asyncio.to_thread(ig_reels_tool, username, limit, details)

    @mcp.tool()
    async def ig_search(
        query: str, kind: str = "posts", limit: int = 12, variants: bool = False
    ) -> dict[str, Any]:
        """Búsqueda en Instagram (posts por keyword o usuarios por typeahead)."""
        return await asyncio.to_thread(ig_search_tool, query, kind, limit, variants)

    @mcp.tool()
    async def ig_comments(post: str, limit: int = 20) -> dict[str, Any]:
        """Comentarios de un post de Instagram (autor, texto y antigüedad)."""
        return await asyncio.to_thread(ig_comments_tool, post, limit)

    @mcp.tool()
    async def fb_page(page: str, limit: int = 12) -> dict[str, Any]:
        """Página de Facebook (info del header + posts visibles)."""
        return await asyncio.to_thread(fb_page_tool, page, limit)

    @mcp.tool()
    async def fb_search(
        query: str, kind: str = "pages", limit: int = 12, variants: bool = False
    ) -> dict[str, Any]:
        """Búsqueda en Facebook (páginas, grupos o personas)."""
        return await asyncio.to_thread(fb_search_tool, query, kind, limit, variants)

    @mcp.tool()
    async def fb_groups_feed(limit: int = 12) -> dict[str, Any]:
        """Posts del feed de los grupos a los que pertenece el usuario."""
        return await asyncio.to_thread(fb_groups_feed_tool, limit)

    return mcp


def run() -> None:
    """Arranca el server por stdio (``argos mcp``)."""
    build_server().run()
