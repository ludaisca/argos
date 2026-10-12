"""CLI: contrato de comandos y exit codes."""

from __future__ import annotations

import json
from typing import Any

import pytest
from typer.testing import CliRunner, Result

import argos.cli as cli_mod
from argos.errors import LoginRequiredError
from argos.platforms.base import PlatformStatus

runner = CliRunner()


def _output(result: Result) -> str:
    text = result.output
    stderr = getattr(result, "stderr", None)
    if stderr:
        text += stderr
    return text


def _stdout(result: Result) -> str:
    value = getattr(result, "stdout", None)
    return value if value is not None else result.output


class DummySession:
    """Context manager mínimo para no abrir un navegador en los tests de CLI."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        pass

    def __enter__(self) -> DummySession:
        return self

    def __exit__(self, *exc_info: object) -> None:
        pass


def _fake_collect(status: str) -> Any:
    def fake(
        config: Any, *, platforms: Any = None, headless: bool = True
    ) -> dict[str, Any]:
        entry = {
            "platform": "instagram",
            "status": status,
            "detail": "detalle de prueba",
            "hint": None,
            "active_backend": None,
            "checked_at": "2026-09-30T00:00:00+00:00",
        }
        return {
            "generated_at": "2026-09-30T00:00:00+00:00",
            "browser": {"ready": True, "detail": "Chrome"},
            "platforms": {"instagram": entry},
        }

    return fake


def test_version_flag() -> None:
    result = runner.invoke(cli_mod.app, ["--version"])
    assert result.exit_code == 0
    assert result.output.startswith("argos ")


def test_doctor_json_needs_login_exits_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli_mod, "collect", _fake_collect("needs-login"))
    result = runner.invoke(cli_mod.app, ["doctor", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["platforms"]["instagram"]["status"] == "needs-login"


def test_doctor_json_error_exits_one(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli_mod, "collect", _fake_collect("error"))
    result = runner.invoke(cli_mod.app, ["doctor", "--json"])
    assert result.exit_code == 1


def test_doctor_text_mode_renders_table(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli_mod, "collect", _fake_collect("ok"))
    result = runner.invoke(cli_mod.app, ["doctor"])
    assert result.exit_code == 0
    assert "instagram" in result.output
    assert "detalle de prueba" in result.output


def test_login_success(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_login(platform: Any, config: Any, **kwargs: Any) -> PlatformStatus:
        return PlatformStatus("instagram", "ok", "sesión válida (argos_test)")

    monkeypatch.setattr(cli_mod, "run_login", fake_login)
    result = runner.invoke(cli_mod.app, ["login", "instagram"])
    assert result.exit_code == 0
    assert "sesión válida" in result.output


def test_login_failure_exits_three(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_login(platform: Any, config: Any, **kwargs: Any) -> PlatformStatus:
        raise LoginRequiredError("no hay sesión", hint="ejecutá `argos login instagram`")

    monkeypatch.setattr(cli_mod, "run_login", fake_login)
    result = runner.invoke(cli_mod.app, ["login", "instagram"])
    assert result.exit_code == 3
    assert "ejecutá" in _output(result)


def test_login_unknown_platform_exits_two() -> None:
    result = runner.invoke(cli_mod.app, ["login", "tiktok"])
    assert result.exit_code == 2
    assert "desconocida" in _output(result)


def test_login_browser_crash_exits_one(monkeypatch: pytest.MonkeyPatch) -> None:
    from playwright.sync_api import Error as PlaywrightError

    def fake_login(platform: Any, config: Any, **kwargs: Any) -> PlatformStatus:
        raise PlaywrightError("boom")

    monkeypatch.setattr(cli_mod, "run_login", fake_login)
    result = runner.invoke(cli_mod.app, ["login", "instagram"])
    assert result.exit_code == 1
    assert "el navegador se cerró o falló" in _output(result)


def test_doctor_unknown_platform_exits_two() -> None:
    result = runner.invoke(
        cli_mod.app, ["doctor", "--platform", "tiktok", "--json"]
    )
    assert result.exit_code == 2
    assert "desconocida" in _output(result)


def test_ig_posts_json_and_out(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    from argos.models import Post
    from argos.platforms.instagram import PostsResult

    def fake_fetch(
        session: Any,
        username: str,
        *,
        limiter: Any,
        pacer: Any,
        limit: int,
        details: bool,
        since: Any,
    ) -> PostsResult:
        return PostsResult(
            posts=[
                Post(
                    id="x",
                    url="https://www.instagram.com/p/x/",
                    likes=10,
                    comments=2,
                )
            ],
            actions=2,
            daily_remaining=39,
        )

    monkeypatch.setattr(cli_mod, "BrowserSession", DummySession)
    monkeypatch.setattr(cli_mod, "fetch_posts", fake_fetch)

    result = runner.invoke(
        cli_mod.app,
        ["ig", "posts", "nasa", "--json", "--limit", "1", "--out", str(tmp_path)],
    )
    assert result.exit_code == 0
    payload = json.loads(_stdout(result))
    assert payload["posts"][0]["likes"] == 10
    assert (tmp_path / "posts.jsonl").exists()


def test_ig_profile_json(monkeypatch: pytest.MonkeyPatch) -> None:
    from argos.models import Profile
    from argos.platforms.instagram import ProfileResult

    def fake_fetch_profile(
        session: Any, username: str, *, limiter: Any, pacer: Any, limit: int
    ) -> ProfileResult:
        return ProfileResult(
            profile=Profile(username="nasa", followers=1000, posts_count=42),
            recent_posts=[],
            actions=1,
            daily_remaining=99,
        )

    monkeypatch.setattr(cli_mod, "BrowserSession", DummySession)
    monkeypatch.setattr(cli_mod, "fetch_profile", fake_fetch_profile)

    result = runner.invoke(cli_mod.app, ["ig", "profile", "nasa", "--json"])
    assert result.exit_code == 0
    payload = json.loads(_stdout(result))
    assert payload["profile"]["username"] == "nasa"
    assert payload["profile"]["followers"] == 1000


def test_ig_posts_rate_limited_exits_four(monkeypatch: pytest.MonkeyPatch) -> None:
    from argos.errors import RateLimitedError

    def fake_fetch(*args: Any, **kwargs: Any) -> Any:
        raise RateLimitedError("cuota diaria agotada", hint="esperá")

    monkeypatch.setattr(cli_mod, "BrowserSession", DummySession)
    monkeypatch.setattr(cli_mod, "fetch_posts", fake_fetch)

    result = runner.invoke(cli_mod.app, ["ig", "posts", "nasa", "--json"])
    assert result.exit_code == 4
    assert "cuota diaria agotada" in _output(result)


def test_ig_posts_human_output(monkeypatch: pytest.MonkeyPatch) -> None:
    """El modo humano debe renderizar sin tabla y con métricas compactas."""
    from argos.models import Post
    from argos.platforms.instagram import PostsResult

    def fake_fetch(*args: Any, **kwargs: Any) -> PostsResult:
        return PostsResult(
            posts=[
                Post(
                    id="x",
                    url="https://www.instagram.com/p/x/",
                    caption="un caption",
                    likes=118_000,
                    comments=842,
                )
            ],
            actions=2,
            daily_remaining=39,
        )

    monkeypatch.setattr(cli_mod, "BrowserSession", DummySession)
    monkeypatch.setattr(cli_mod, "fetch_posts", fake_fetch)

    result = runner.invoke(cli_mod.app, ["ig", "posts", "nasa"])
    assert result.exit_code == 0
    text = _output(result)
    assert "118K likes" in text
    assert "https://www.instagram.com/p/x/" in text


def test_ig_hashtag_json(monkeypatch: pytest.MonkeyPatch) -> None:
    from argos.models import Post
    from argos.platforms.instagram import PostsResult

    def fake_fetch(*args: Any, **kwargs: Any) -> PostsResult:
        return PostsResult(
            posts=[Post(id="abc", url="https://www.instagram.com/p/abc/", views=4700000)],
            actions=1,
            daily_remaining=50,
        )

    monkeypatch.setattr(cli_mod, "BrowserSession", DummySession)
    monkeypatch.setattr(cli_mod, "fetch_hashtag", fake_fetch)

    result = runner.invoke(cli_mod.app, ["ig", "hashtag", "#nasa", "--json"])
    assert result.exit_code == 0
    payload = json.loads(_stdout(result))
    assert payload["posts"][0]["views"] == 4_700_000


def test_ig_search_users_json(monkeypatch: pytest.MonkeyPatch) -> None:
    from argos.models import SearchHit
    from argos.platforms.instagram import SearchResult

    def fake_search(*args: Any, **kwargs: Any) -> SearchResult:
        return SearchResult(
            hits=[
                SearchHit(
                    type="user",
                    username="nasa",
                    name="NASA",
                    url="https://www.instagram.com/nasa/",
                    followers=104_000_000,
                )
            ],
            actions=2,
            daily_remaining=48,
        )

    monkeypatch.setattr(cli_mod, "BrowserSession", DummySession)
    monkeypatch.setattr(cli_mod, "search", fake_search)

    result = runner.invoke(
        cli_mod.app, ["ig", "search", "nasa", "--type", "users", "--json"]
    )
    assert result.exit_code == 0
    payload = json.loads(_stdout(result))
    assert payload["users"][0]["username"] == "nasa"
    assert payload["users"][0]["followers"] == 104_000_000


def test_ig_comments_json(monkeypatch: pytest.MonkeyPatch) -> None:
    from argos.models import Comment
    from argos.platforms.instagram import CommentsResult

    def fake_fetch(*args: Any, **kwargs: Any) -> CommentsResult:
        return CommentsResult(
            comments=[
                Comment(
                    id="18116683306989676",
                    url="https://www.instagram.com/p/x/c/18116683306989676/",
                    post_url="https://www.instagram.com/p/x/",
                    author="alguien",
                    text="hola",
                    age_text="5d",
                )
            ],
            actions=1,
            daily_remaining=47,
        )

    monkeypatch.setattr(cli_mod, "BrowserSession", DummySession)
    monkeypatch.setattr(cli_mod, "fetch_comments", fake_fetch)

    result = runner.invoke(
        cli_mod.app, ["ig", "comments", "https://www.instagram.com/p/x/", "--json"]
    )
    assert result.exit_code == 0
    payload = json.loads(_stdout(result))
    assert payload["comments"][0]["author"] == "alguien"


def test_fb_page_json(monkeypatch: pytest.MonkeyPatch) -> None:
    from argos.models import Post, Profile
    from argos.platforms.facebook import PageResult

    def fake_fetch(*args: Any, **kwargs: Any) -> PageResult:
        return PageResult(
            profile=Profile(
                platform="facebook", username="NASA", followers=28_000_000
            ),
            posts=[
                Post(
                    platform="facebook",
                    id="abc123",
                    url="https://www.facebook.com/NASA/",
                    caption="Un post",
                    likes=474,
                    comments=21,
                    shares=68,
                )
            ],
            actions=1,
            daily_remaining=60,
        )

    monkeypatch.setattr(cli_mod, "BrowserSession", DummySession)
    monkeypatch.setattr(cli_mod, "fetch_page", fake_fetch)

    result = runner.invoke(cli_mod.app, ["fb", "page", "NASA", "--json"])
    assert result.exit_code == 0
    payload = json.loads(_stdout(result))
    assert payload["profile"]["followers"] == 28_000_000
    assert payload["posts"][0]["shares"] == 68


def test_fb_search_json(monkeypatch: pytest.MonkeyPatch) -> None:
    from argos.models import SearchHit
    from argos.platforms.facebook.flows import SearchResult

    def fake_search(*args: Any, **kwargs: Any) -> SearchResult:
        return SearchResult(
            hits=[
                SearchHit(
                    platform="facebook",
                    type="page",
                    username="NASA",
                    name="NASA",
                    url="https://www.facebook.com/NASA/",
                    followers=28_000_000,
                )
            ],
            actions=1,
            daily_remaining=59,
        )

    monkeypatch.setattr(cli_mod, "BrowserSession", DummySession)
    monkeypatch.setattr(cli_mod, "fb_search", fake_search)

    result = runner.invoke(
        cli_mod.app, ["fb", "search", "nasa", "--type", "pages", "--json"]
    )
    assert result.exit_code == 0
    payload = json.loads(_stdout(result))
    assert payload["results"][0]["username"] == "NASA"


def test_fb_groups_feed_human(monkeypatch: pytest.MonkeyPatch) -> None:
    from argos.platforms.facebook import PostsResult

    def fake_fetch(*args: Any, **kwargs: Any) -> PostsResult:
        return PostsResult(
            posts=[],
            actions=1,
            daily_remaining=58,
            note="sin novedades en tus grupos",
        )

    monkeypatch.setattr(cli_mod, "BrowserSession", DummySession)
    monkeypatch.setattr(cli_mod, "fetch_group_feed", fake_fetch)

    result = runner.invoke(cli_mod.app, ["fb", "groups-feed"])
    assert result.exit_code == 0
    assert "sin novedades" in _output(result)


def test_quota_json() -> None:
    result = runner.invoke(cli_mod.app, ["quota", "--json"])
    assert result.exit_code == 0
    payload = json.loads(_stdout(result))
    assert set(payload) == {"instagram", "facebook", "youtube", "linkedin", "x"}
    assert payload["instagram"]["daily_limit"] == 400
    assert payload["instagram"]["remaining"] == 400  # estado fresco en tests


def test_quota_human() -> None:
    result = runner.invoke(cli_mod.app, ["quota"])
    assert result.exit_code == 0
    assert "instagram" in result.output
    assert "facebook" in result.output


def test_configure_ig_cookies(monkeypatch: pytest.MonkeyPatch) -> None:
    from argos.config import ArgosConfig

    payload = '[{"name":"sessionid","value":"abc","domain":".instagram.com","path":"/"}]'
    result = runner.invoke(
        cli_mod.app, ["configure", "ig-cookies", "--value", payload]
    )
    assert result.exit_code == 0
    stored = ArgosConfig.load().get("ig_cookies")
    assert stored == [
        {"name": "sessionid", "value": "abc", "domain": ".instagram.com", "path": "/"}
    ]


def test_configure_unknown_key() -> None:
    result = runner.invoke(cli_mod.app, ["configure", "nope"])
    assert result.exit_code == 2


def test_cookies_export_json(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeContext:
        def cookies(self) -> list[dict[str, object]]:
            return [
                {
                    "name": "sessionid",
                    "value": "abc",
                    "domain": ".instagram.com",
                    "path": "/",
                    "expires": -1,
                }
            ]

    class FakeSession:
        context = FakeContext()

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        def __enter__(self) -> FakeSession:
            return self

        def __exit__(self, *exc_info: object) -> None:
            pass

    monkeypatch.setattr(cli_mod, "BrowserSession", FakeSession)
    result = runner.invoke(cli_mod.app, ["cookies", "instagram", "--json"])
    assert result.exit_code == 0
    payload = json.loads(_stdout(result))
    assert payload[0]["name"] == "sessionid"


def test_report_cli(tmp_path: Any) -> None:
    from pathlib import Path as _Path

    from argos.models import Post
    from argos.store import append_unique_jsonl

    out = _Path(tmp_path) / "job"
    out.mkdir()
    append_unique_jsonl(
        out / "posts.jsonl",
        [Post(platform="instagram", id="a", url="u", likes=5)],
        ("platform", "id"),
    )
    result = runner.invoke(cli_mod.app, ["report", str(out), "--json"])
    assert result.exit_code == 0
    payload = json.loads(_stdout(result))
    assert _Path(payload["markdown"]).exists()


def test_research_example() -> None:
    result = runner.invoke(cli_mod.app, ["research", "--example"])
    assert result.exit_code == 0
    assert "targets:" in result.output


def test_research_missing_plan_exits_two() -> None:
    result = runner.invoke(cli_mod.app, ["research"])
    assert result.exit_code == 2
    assert "plan" in _output(result)


def test_agent_plan_cli(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    from argos.agent import Brief

    monkeypatch.setenv("ARGOS_LLM_API_KEY", "k")
    monkeypatch.setattr(
        "argos.agent.resolve_brief", lambda path=None: Brief(name="job", objective="x")
    )
    monkeypatch.setattr(
        "argos.agent.plan_targets",
        lambda settings, brief: [{"type": "ig_profile", "value": "nasa", "limit": 3}],
    )
    result = runner.invoke(cli_mod.app, ["agent", "plan", "--json"])
    assert result.exit_code == 0
    payload = json.loads(_stdout(result))
    assert payload["targets"][0]["type"] == "ig_profile"


def test_agent_run_cli(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    from argos.agent import AgentRunResult, Brief

    monkeypatch.setenv("ARGOS_LLM_API_KEY", "k")

    def fake_once(
        config: Any, *, brief: Any, base_dir: Any, settings: Any, webhook_url: Any = None
    ) -> AgentRunResult:
        return AgentRunResult(
            run_dir=tmp_path / "run",
            plan=[{"type": "ig_profile", "value": "nasa", "limit": 3}],
            plan_source="brief",
            job_dir=str(tmp_path / "job"),
            analysis_path=None,
            results=[{"target": "ig_profile:nasa", "status": "ok"}],
        )

    monkeypatch.setattr(
        "argos.agent.resolve_brief", lambda path=None: Brief(name="j", objective="x")
    )
    monkeypatch.setattr("argos.agent.run_once", fake_once)

    result = runner.invoke(cli_mod.app, ["agent", "run", "--json"])
    assert result.exit_code == 0
    payload = json.loads(_stdout(result))
    assert payload["results"][0]["status"] == "ok"


def test_agent_requires_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ARGOS_LLM_API_KEY", raising=False)
    result = runner.invoke(cli_mod.app, ["agent", "plan"])
    assert result.exit_code == 2
    assert "LLM" in _output(result)


def test_agent_daemon_cli(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ARGOS_LLM_API_KEY", "k")
    calls: list[dict[str, Any]] = []

    def fake_daemon(config: Any, **kwargs: Any) -> list[Any]:
        calls.append(kwargs)
        return []

    monkeypatch.setattr("argos.agent.run_daemon", fake_daemon)
    result = runner.invoke(cli_mod.app, ["agent", "daemon", "--max-runs", "1"])
    assert result.exit_code == 0
    assert len(calls) == 1
    assert "brief_provider" in calls[0]


def test_ui_command_calls_serve(monkeypatch: pytest.MonkeyPatch) -> None:
    import argos.web

    called: dict[str, Any] = {}

    def fake_serve(**kwargs: Any) -> None:
        called.update(kwargs)

    monkeypatch.setattr(argos.web, "serve", fake_serve)
    result = runner.invoke(cli_mod.app, ["ui", "--no-open", "--port", "9999"])
    assert result.exit_code == 0
    assert called["port"] == 9999
    assert called["open_browser"] is False


def test_leads_enrich_cli_passes_batch_flags(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    csv_path = tmp_path / "leads.csv"
    csv_path.write_text("Nombre,Correo\nAna,ana@clinicasonrisa.mx\n", encoding="utf-8")
    captured: dict[str, Any] = {}

    def fake_enrich(leads: Any, **kwargs: Any) -> dict[str, Any]:
        captured.update(kwargs)
        return {"rows": 1, "counts": {"medico": 1, "dudoso": 0, "no": 0}, "csv": "x"}

    monkeypatch.setattr("argos.leads.enrich_batch", fake_enrich)
    result = runner.invoke(
        cli_mod.app,
        [
            "leads",
            "enrich",
            str(csv_path),
            "--batch-size",
            "2",
            "--pause-seconds",
            "5",
            "--no-searxng",
            "--no-facebook",
            "--no-nominatim",
        ],
    )
    assert result.exit_code == 0, result.output
    assert captured["batch_size"] == 2
    assert captured["pause_seconds"] == 5.0
    assert captured["use_searxng"] is False
    assert captured["use_facebook"] is False
    assert captured["use_gmaps"] is None  # sin flag: se respeta la config
    assert captured["use_nominatim"] is False
