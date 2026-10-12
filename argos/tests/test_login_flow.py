"""Flujo de login asistido, con BrowserSession y plataforma dobles."""

from __future__ import annotations

from typing import Any

import pytest
from playwright.sync_api import Error as PlaywrightError

import argos.platforms.base as base_mod
from argos.browser.checkpoints import Problem
from argos.config import ArgosConfig
from argos.errors import CheckpointError, LoginRequiredError
from argos.platforms.base import Platform, PlatformStatus, run_login


class FakePage:
    def goto(self, url: str, **_kwargs: object) -> None:
        pass


class FakeSession:
    """Doble de BrowserSession; el comportamiento se controla por atributos de clase."""

    cookies_after: int = 0
    problem: Problem | None = None

    def __init__(self, platform: str, config: ArgosConfig, **kwargs: Any) -> None:
        self._calls = 0
        self.page = FakePage()

    def __enter__(self) -> FakeSession:
        return self

    def __exit__(self, *exc_info: object) -> None:
        pass

    def goto(self, url: str, **_kwargs: object) -> None:
        pass

    def cookies(self) -> dict[str, str]:
        self._calls += 1
        if self._calls > type(self).cookies_after:
            return {"sessionid": "s", "ds_user_id": "1"}
        return {}

    def inspect(self) -> Problem | None:
        return type(self).problem


class FakePlatform(Platform):
    name = "fake"
    title = "Fake"
    login_url = "https://example.com/"
    session_cookies = ("sessionid", "ds_user_id")

    def probe(self, session: Any, *, navigate: bool = True) -> PlatformStatus:
        jar = session.cookies()
        if all(name in jar for name in self.session_cookies):
            return PlatformStatus(self.name, "ok", "sesión válida")
        return PlatformStatus(self.name, "needs-login", "faltan cookies")


@pytest.fixture
def patched_session(monkeypatch: pytest.MonkeyPatch) -> type[FakeSession]:
    FakeSession.cookies_after = 0
    FakeSession.problem = None
    monkeypatch.setattr(base_mod, "BrowserSession", FakeSession)
    return FakeSession


def test_run_login_detects_session(patched_session: type[FakeSession]) -> None:
    status = run_login(
        FakePlatform(),
        ArgosConfig.load(),
        timeout_s=1,
        poll_interval_s=0.001,
        reprobe_interval_s=0.0,
    )
    assert status.status == "ok"


def test_run_login_times_out_without_session(patched_session: type[FakeSession]) -> None:
    patched_session.cookies_after = 10**9
    with pytest.raises(LoginRequiredError, match="no se detectó"):
        run_login(
            FakePlatform(),
            ArgosConfig.load(),
            timeout_s=0.05,
            poll_interval_s=0.005,
            reprobe_interval_s=0.0,
        )


def test_run_login_reports_pending_checkpoint(patched_session: type[FakeSession]) -> None:
    patched_session.cookies_after = 10**9
    patched_session.problem = Problem("checkpoint", "URL de verificación")
    with pytest.raises(CheckpointError, match="verificación pendiente"):
        run_login(
            FakePlatform(),
            ArgosConfig.load(),
            timeout_s=0.05,
            poll_interval_s=0.005,
            reprobe_interval_s=0.0,
        )


def test_run_login_waits_for_cookies_to_appear(patched_session: type[FakeSession]) -> None:
    patched_session.cookies_after = 3
    status = run_login(
        FakePlatform(),
        ArgosConfig.load(),
        timeout_s=1,
        poll_interval_s=0.001,
        reprobe_interval_s=0.0,
    )
    assert status.status == "ok"


def test_run_login_handles_closed_window(monkeypatch: pytest.MonkeyPatch) -> None:
    """Cerrar la ventana a mitad del login => error claro, no un traceback."""

    class ClosedWindowSession(FakeSession):
        def cookies(self) -> dict[str, str]:
            raise PlaywrightError("Target page, context or browser has been closed")

    monkeypatch.setattr(base_mod, "BrowserSession", ClosedWindowSession)
    with pytest.raises(LoginRequiredError, match="se cerró"):
        run_login(
            FakePlatform(),
            ArgosConfig.load(),
            timeout_s=1,
            poll_interval_s=0.001,
            reprobe_interval_s=0.0,
        )
