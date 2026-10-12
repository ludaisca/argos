"""Investigación multi-objetivo: plan YAML y corrida."""

from __future__ import annotations

import textwrap
from pathlib import Path
from typing import Any

import pytest

import argos.research as research_mod
from argos.errors import RateLimitedError, UsageError
from argos.models import Post, Profile
from argos.research import EXAMPLE_PLAN, load_plan, run_research


def _write_plan(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "plan.yaml"
    path.write_text(textwrap.dedent(body), encoding="utf-8")
    return path


def test_load_plan_valid(tmp_path: Path) -> None:
    path = _write_plan(
        tmp_path,
        """
        job: "Mi job"
        headless: false
        targets:
          - type: ig_profile
            value: nasa
            limit: 5
          - type: fb_groups_feed
        """,
    )
    job, headless, targets = load_plan(path)
    assert job == "Mi job"
    assert headless is False
    assert len(targets) == 2
    assert targets[0].type == "ig_profile"
    assert targets[0].platform == "instagram"
    assert targets[0].limit == 5
    assert targets[1].platform == "facebook"


def test_load_plan_errors(tmp_path: Path) -> None:
    with pytest.raises(UsageError, match="targets"):
        load_plan(_write_plan(tmp_path, "job: x\n"))
    with pytest.raises(UsageError, match="desconocido"):
        load_plan(_write_plan(tmp_path, "targets:\n  - type: nope\n    value: x\n"))
    with pytest.raises(UsageError, match="necesita"):
        load_plan(_write_plan(tmp_path, "targets:\n  - type: ig_profile\n"))


def test_example_plan_is_valid(tmp_path: Path) -> None:
    path = tmp_path / "example.yaml"
    path.write_text(EXAMPLE_PLAN, encoding="utf-8")
    _job, _headless, targets = load_plan(path)
    assert targets


class DummySession:
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        pass

    def __enter__(self) -> DummySession:
        return self

    def __exit__(self, *exc_info: object) -> None:
        pass


def test_run_research_ok(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from argos.platforms.facebook import PageResult
    from argos.platforms.instagram import ProfileResult

    def fake_ig_profile(
        session: Any, username: str, *, limiter: Any, pacer: Any, limit: int
    ) -> ProfileResult:
        return ProfileResult(
            profile=Profile(platform="instagram", username=username, followers=5),
            recent_posts=[Post(platform="instagram", id="p1", url="https://x/p1")],
            actions=1,
            daily_remaining=99,
        )

    def fake_fb_page(
        session: Any, page: str, *, limiter: Any, pacer: Any, limit: int
    ) -> PageResult:
        return PageResult(
            profile=Profile(platform="facebook", username=page),
            posts=[Post(platform="facebook", id="f1", url="https://y/f1")],
            actions=1,
            daily_remaining=98,
        )

    monkeypatch.setattr(research_mod, "BrowserSession", DummySession)
    monkeypatch.setattr("argos.platforms.instagram.fetch_profile", fake_ig_profile)
    monkeypatch.setattr("argos.platforms.facebook.fetch_page", fake_fb_page)

    plan = _write_plan(
        tmp_path,
        """
        job: "test job"
        targets:
          - type: ig_profile
            value: nasa
          - type: fb_page
            value: NASA
        """,
    )
    result = run_research(plan, base_dir=tmp_path / "out")

    assert [item["status"] for item in result["results"]] == ["ok", "ok"]
    job_dir = Path(result["job_dir"])
    assert (job_dir / "posts.jsonl").exists()
    assert (job_dir / "profiles.jsonl").exists()
    assert (job_dir / "run.json").exists()
    assert result["report"] is not None
    assert Path(result["report"]["markdown"]).exists()


def test_run_research_stops_platform_on_rate_limit(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def fake_ig_profile(
        session: Any, username: str, *, limiter: Any, pacer: Any, limit: int
    ) -> Any:
        raise RateLimitedError("cuota agotada", hint="esperá")

    monkeypatch.setattr(research_mod, "BrowserSession", DummySession)
    monkeypatch.setattr("argos.platforms.instagram.fetch_profile", fake_ig_profile)

    plan = _write_plan(
        tmp_path,
        """
        targets:
          - type: ig_profile
            value: a
          - type: ig_profile
            value: b
        """,
    )
    result = run_research(plan, base_dir=tmp_path / "out")

    assert [item["status"] for item in result["results"]] == ["stopped", "skipped"]
    assert result["report"] is None  # no hubo datos
