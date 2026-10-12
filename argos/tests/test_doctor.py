"""doctor.collect: degradación elegante sin navegador y ante fallos."""

from __future__ import annotations

from typing import Any

import pytest
from playwright.sync_api import Error as PlaywrightError

import argos.doctor as doctor_mod
from argos.config import ArgosConfig
from argos.doctor import collect
from argos.platforms.base import PlatformStatus


def test_collect_off_when_browser_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        doctor_mod, "browser_readiness", lambda: (False, "navegador no instalado")
    )
    data = collect(ArgosConfig.load())
    assert data["browser"]["ready"] is False
    assert set(data["platforms"]) == {"instagram", "facebook", "youtube", "linkedin", "x"}
    for entry in data["platforms"].values():
        assert entry["status"] == "off"
        assert "playwright install chromium" in str(entry["hint"])


def test_collect_survives_browser_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(doctor_mod, "browser_readiness", lambda: (True, "chrome"))

    class BoomSession:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        def __enter__(self) -> BoomSession:
            raise PlaywrightError("boom")

        def __exit__(self, *exc_info: object) -> None:
            pass

    monkeypatch.setattr(doctor_mod, "BrowserSession", BoomSession)
    data = collect(ArgosConfig.load(), platforms=["instagram"])
    entry = data["platforms"]["instagram"]
    assert entry["status"] == "error"
    assert "boom" in str(entry["detail"])


def test_collect_ok_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(doctor_mod, "browser_readiness", lambda: (True, "chrome"))

    class FakeContext:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        def __enter__(self) -> FakeContext:
            return self

        def __exit__(self, *exc_info: object) -> None:
            pass

    class FakePlatform:
        def probe(self, session: Any, *, navigate: bool = True) -> PlatformStatus:
            return PlatformStatus(
                "instagram", "ok", "sesión válida", active_backend="internal-api"
            )

    monkeypatch.setattr(doctor_mod, "BrowserSession", FakeContext)
    monkeypatch.setattr(doctor_mod, "get_platform", lambda name: FakePlatform())
    data = collect(ArgosConfig.load(), platforms=["instagram"])
    entry = data["platforms"]["instagram"]
    assert entry["status"] == "ok"
    assert entry["active_backend"] == "internal-api"
    assert "checked_at" in entry
