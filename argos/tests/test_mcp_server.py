"""Servidor MCP: tools expuestas y serialización."""

from __future__ import annotations

import pytest

mcp = pytest.importorskip("mcp")


def test_build_server_exposes_tools() -> None:
    import asyncio
    from concurrent.futures import ThreadPoolExecutor

    from argos.mcp_server import build_server

    server = build_server()
    # list_tools es async; lo corremos en un hilo con loop propio para no chocar
    # con el loop que pytest puede dejar corriendo durante la suite completa.
    with ThreadPoolExecutor(max_workers=1) as pool:
        tools = pool.submit(lambda: asyncio.run(server.list_tools())).result()

    names = {tool.name for tool in tools}
    expected = {
        "doctor",
        "quota",
        "ig_profile",
        "ig_posts",
        "ig_hashtag",
        "ig_reels",
        "ig_search",
        "ig_comments",
        "fb_page",
        "fb_search",
        "fb_groups_feed",
    }
    assert expected <= names


def test_quota_tool_returns_report(isolated_home) -> None:
    from argos.mcp_server import quota_tool

    report = quota_tool()
    assert set(report) == {"instagram", "facebook", "youtube", "linkedin", "x"}
    assert report["instagram"]["daily_limit"] == 400


def test_ig_profile_tool_wraps_flow(monkeypatch: pytest.MonkeyPatch) -> None:
    from argos.mcp_server import ig_profile_tool
    from argos.models import Profile
    from argos.platforms.instagram import ProfileResult

    class DummySession:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        def __enter__(self) -> DummySession:
            return self

        def __exit__(self, *exc_info: object) -> None:
            pass

    def fake_fetch(
        session: object,
        username: str,
        *,
        limiter: object,
        pacer: object,
        limit: int,
    ) -> ProfileResult:
        return ProfileResult(
            profile=Profile(platform="instagram", username=username, followers=7),
            recent_posts=[],
            actions=1,
            daily_remaining=99,
        )

    monkeypatch.setattr("argos.mcp_server.BrowserSession", DummySession)
    monkeypatch.setattr("argos.platforms.instagram.fetch_profile", fake_fetch)

    payload = ig_profile_tool("nasa", limit=5)
    assert payload["profile"]["username"] == "nasa"
    assert payload["profile"]["followers"] == 7
    assert payload["actions"] == 1
