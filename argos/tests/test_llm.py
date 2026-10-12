"""Cliente LLM: resolución de settings, request y parseo."""

from __future__ import annotations

import json
from typing import Any

import pytest

from argos.llm import (
    LLMError,
    LLMSettings,
    chat,
    parse_json_response,
    resolve_llm_settings,
)


def test_resolve_settings_from_env(monkeypatch: pytest.MonkeyPatch, isolated_home) -> None:
    monkeypatch.setenv("ARGOS_LLM_API_KEY", "k")
    monkeypatch.setenv("ARGOS_LLM_BASE_URL", "https://api.test/v1/")
    monkeypatch.setenv("ARGOS_LLM_MODEL", "modelo")
    settings = resolve_llm_settings()
    assert settings == LLMSettings(
        api_key="k", base_url="https://api.test/v1", model="modelo"
    )


def test_resolve_settings_none_without_key(
    monkeypatch: pytest.MonkeyPatch, isolated_home
) -> None:
    monkeypatch.delenv("ARGOS_LLM_API_KEY", raising=False)
    assert resolve_llm_settings() is None


def test_resolve_settings_from_config(isolated_home, monkeypatch: pytest.MonkeyPatch) -> None:
    from argos.config import ArgosConfig

    monkeypatch.delenv("ARGOS_LLM_API_KEY", raising=False)
    config = ArgosConfig.load()
    config.set("llm_api_key", "cfg-key")
    settings = resolve_llm_settings(config)
    assert settings is not None
    assert settings.api_key == "cfg-key"
    assert settings.base_url == "https://api.openai.com/v1"  # default


class FakeResponse:
    def __init__(self, status_code: int, payload: dict[str, Any]) -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = json.dumps(payload)

    @property
    def ok(self) -> bool:
        return 200 <= self.status_code < 300

    def json(self) -> dict[str, Any]:
        return self._payload


def test_chat_parses_content(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: dict[str, Any] = {}

    def fake_post(url: str, headers: Any = None, json: Any = None, timeout: Any = None):
        calls["url"] = url
        calls["payload"] = json
        return FakeResponse(200, {"choices": [{"message": {"content": "hola"}}]})

    monkeypatch.setattr("argos.llm.requests.post", fake_post)
    out = chat(
        LLMSettings(api_key="k", base_url="https://api.test/v1", model="m"),
        [{"role": "user", "content": "x"}],
        json_mode=True,
    )
    assert out == "hola"
    assert calls["url"] == "https://api.test/v1/chat/completions"
    assert calls["payload"]["response_format"] == {"type": "json_object"}
    assert calls["payload"]["model"] == "m"


def test_chat_retries_without_json_mode_on_400(monkeypatch: pytest.MonkeyPatch) -> None:
    attempts: list[dict[str, Any]] = []

    def fake_post(url: str, headers: Any = None, json: Any = None, timeout: Any = None):
        attempts.append(dict(json))
        if "response_format" in json:
            return FakeResponse(400, {"error": "no soportado"})
        return FakeResponse(200, {"choices": [{"message": {"content": "ok"}}]})

    monkeypatch.setattr("argos.llm.requests.post", fake_post)
    out = chat(LLMSettings(api_key="k"), [{"role": "user", "content": "x"}], json_mode=True)
    assert out == "ok"
    assert len(attempts) == 2 and "response_format" not in attempts[1]


def test_chat_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_post(url: str, headers: Any = None, json: Any = None, timeout: Any = None):
        return FakeResponse(500, {"error": "boom"})

    monkeypatch.setattr("argos.llm.requests.post", fake_post)
    with pytest.raises(LLMError, match="HTTP 500"):
        chat(LLMSettings(api_key="k"), [{"role": "user", "content": "x"}])


@pytest.mark.parametrize(
    "content",
    ['{"a": 1}', '```json\n{"a": 1}\n```', '```\n{"a": 1}\n```', '  {"a": 1}  '],
)
def test_parse_json_response(content: str) -> None:
    assert parse_json_response(content) == {"a": 1}


def test_parse_json_response_invalid() -> None:
    with pytest.raises(LLMError):
        parse_json_response("esto no es json")
