"""Probe de X (Twitter) — requiere sesión del humano."""

from __future__ import annotations

import contextlib

from playwright.sync_api import Error as PlaywrightError

from argos.browser.session import BrowserSession
from argos.platforms.base import Platform, PlatformStatus
from argos.platforms.x.extract import is_login_wall, me_handle

_BASE = "https://x.com"
_HOME = f"{_BASE}/home"


class XPlatform(Platform):
    name = "x"
    title = "X (Twitter)"
    login_url = f"{_BASE}/i/flow/login"
    session_cookies = ("auth_token", "ct0")
    backends = ("dom",)

    def probe(self, session: BrowserSession, *, navigate: bool = True) -> PlatformStatus:
        page = session.page
        if navigate or not page.url.startswith(_BASE):
            try:
                session.goto(_HOME)
            except PlaywrightError as exc:
                # X rechaza la carga directa sin sesión (ERR_HTTP_RESPONSE_CODE_FAILURE)
                return PlatformStatus(
                    self.name,
                    "needs-login",
                    f"X no cargó sin sesión ({str(exc)[:60]})",
                    hint=self.login_hint(),
                )

        problem = session.inspect()
        if problem is not None and problem.kind != "login":
            return self._problem_status(problem)

        with contextlib.suppress(PlaywrightError):
            page.wait_for_timeout(1800)

        if is_login_wall(page):
            return PlatformStatus(
                self.name,
                "needs-login",
                "X muestra login (la home requiere sesión)",
                hint=self.login_hint(),
            )
        handle = me_handle(page)
        if handle:
            return PlatformStatus(
                self.name, "ok", f"sesión válida (@{handle})", active_backend="dom"
            )
        if "/home" in page.url:
            return PlatformStatus(self.name, "ok", "sesión válida (home cargó)")
        return PlatformStatus(
            self.name,
            "error",
            f"no se pudo confirmar la sesión (url={page.url[:80]})",
            hint=self.login_hint(),
        )
