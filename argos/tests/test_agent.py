"""Agente autónomo: brief, plan, contexto, corrida y daemon."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

import argos.agent as agent_mod
from argos.agent import (
    AgentRunResult,
    Brief,
    build_context,
    load_brief,
    plan_targets,
    run_daemon,
    run_once,
)
from argos.config import ArgosConfig
from argos.errors import ArgosError, UsageError
from argos.llm import LLMError, LLMSettings
from argos.models import Post, Profile
from argos.store import append_unique_jsonl

SETTINGS = LLMSettings(api_key="k")


def test_load_brief_from_yaml(tmp_path: Path) -> None:
    path = tmp_path / "brief.yaml"
    path.write_text(
        "job: J\nobjective: investigar X\nquestions:\n  - q1\n  - q2\n",
        encoding="utf-8",
    )
    brief = load_brief(path=path)
    assert brief.name == "J"
    assert brief.objective == "investigar X"
    assert brief.questions == ["q1", "q2"]


def test_load_brief_from_text() -> None:
    brief = load_brief(text="algo simple")
    assert brief.objective == "algo simple"
    assert brief.name == "research"


def test_load_brief_requires_objective() -> None:
    with pytest.raises(UsageError):
        load_brief(text="   ")


def test_plan_targets_validates_and_clamps(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_chat(settings: Any, messages: Any, **kwargs: Any) -> str:
        return json.dumps(
            {
                "targets": [
                    {"type": "ig_hashtag", "value": "deepseek", "limit": 99},
                    {"type": "fb_search", "value": "deepseek", "kind": "pages"},
                ]
            }
        )

    monkeypatch.setattr(agent_mod, "chat", fake_chat)
    plan = plan_targets(SETTINGS, Brief(objective="x"))
    assert plan[0] == {"type": "ig_hashtag", "value": "deepseek", "limit": 20}
    assert plan[1]["kind"] == "pages"


def test_plan_targets_rejects_unknown_type(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        agent_mod, "chat", lambda *a, **k: json.dumps({"targets": [{"type": "nope"}]})
    )
    with pytest.raises(LLMError, match="no es válido"):
        plan_targets(SETTINGS, Brief(objective="x"))


def test_build_context(tmp_path: Path) -> None:
    job = tmp_path / "job"
    job.mkdir()
    append_unique_jsonl(
        job / "posts.jsonl",
        [Post(platform="instagram", id="a", url="u", author="nasa", caption="hola", likes=5)],
        ("platform", "id"),
    )
    append_unique_jsonl(
        job / "profiles.jsonl",
        [Profile(platform="instagram", username="nasa", followers=10)],
        ("platform", "username"),
    )
    context = build_context(job)
    assert "PERFILES" in context
    assert "@nasa" in context
    assert "POSTS" in context


def test_run_once_with_explicit_targets(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    def fake_run_research(plan_path: Path, *, base_dir: Path, config: ArgosConfig):
        job_dir = Path(base_dir) / "job"
        job_dir.mkdir(parents=True)
        append_unique_jsonl(
            job_dir / "posts.jsonl",
            [Post(platform="instagram", id="a", url="u", likes=1)],
            ("platform", "id"),
        )
        return {
            "job_dir": str(job_dir),
            "results": [{"target": "x", "status": "ok"}],
            "report": None,
        }

    monkeypatch.setattr(agent_mod, "run_research", fake_run_research)
    monkeypatch.setattr(agent_mod, "analyze", lambda settings, brief, context: "# Análisis\n")

    brief = Brief(
        name="test",
        objective="o",
        targets=[{"type": "ig_profile", "value": "nasa", "limit": 3}],
    )
    result = run_once(
        ArgosConfig.load(), brief=brief, base_dir=tmp_path / "runs", settings=SETTINGS
    )

    assert result.plan_source == "brief"
    assert (result.run_dir / "plan.yaml").exists()
    assert result.analysis_path is not None and result.analysis_path.exists()
    manifest = json.loads((result.run_dir / "run.json").read_text(encoding="utf-8"))
    assert manifest["plan"] == brief.targets


def test_run_once_plan_empty_raises(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(agent_mod, "plan_targets", lambda settings, brief: [])
    with pytest.raises(ArgosError, match="vacío"):
        run_once(
            ArgosConfig.load(),
            brief=Brief(objective="x"),
            base_dir=tmp_path / "runs",
            settings=SETTINGS,
        )


def test_run_daemon_max_runs(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls: list[int] = []

    def fake_once(*args: Any, **kwargs: Any) -> AgentRunResult:
        calls.append(1)
        return AgentRunResult(run_dir=tmp_path, plan=[], plan_source="brief")

    monkeypatch.setattr(agent_mod, "run_once", fake_once)
    runs = run_daemon(
        ArgosConfig.load(),
        brief=Brief(objective="x"),
        base_dir=tmp_path / "runs",
        settings=SETTINGS,
        interval_hours=1,
        max_runs=2,
        sleep_fn=lambda _seconds: None,
    )
    assert len(runs) == 2
    assert len(calls) == 2


def test_apply_env_cookies_from_dir(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, isolated_home
) -> None:
    cookies_dir = tmp_path / "cookies"
    cookies_dir.mkdir()
    (cookies_dir / "instagram-cookies.json").write_text(
        json.dumps([{"name": "sessionid", "value": "abc", "domain": ".instagram.com"}]),
        encoding="utf-8",
    )
    monkeypatch.setenv("ARGOS_COOKIES_DIR", str(cookies_dir))
    from argos.agent import apply_env_cookies

    config = ArgosConfig.load()
    imported = apply_env_cookies(config)
    assert imported == ["instagram"]
    stored = config.get("ig_cookies")
    assert isinstance(stored, list) and stored[0]["name"] == "sessionid"
