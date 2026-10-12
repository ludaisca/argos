"""Probe de LinkedIn (requiere sesión del humano)."""

from __future__ import annotations

import contextlib

from playwright.sync_api import Error as PlaywrightError

from argos.browser.session import BrowserSession
from argos.platforms.base import Platform, PlatformStatus
from argos.platforms.linkedin.extract import is_login_wall, me_name

_BASE = "https://www.linkedin.com"
_FEED = f"{_BASE}/feed/"


class LinkedInPlatform(Platform):
    name = "linkedin"
    title = "LinkedIn"
    login_url = f"{_BASE}/login"
    session_cookies = ("li_at",)
    backends = ("dom",)

    def probe(self, session: BrowserSession, *, navigate: bool = True) -> PlatformStatus:
        page = session.page
        if navigate or not page.url.startswith(_BASE):
            session.goto(_FEED)

        problem = session.inspect()
        if problem is not None and problem.kind != "login":
            return self._problem_status(problem)

        with contextlib.suppress(PlaywrightError):
            page.wait_for_timeout(1500)

        if is_login_wall(page):
            return PlatformStatus(
                self.name,
                "needs-login",
                "LinkedIn muestra login/authwall",
                hint=self.login_hint(),
            )
        name = me_name(page)
        if name:
            return PlatformStatus(
                self.name, "ok", f"sesión válida ({name})", active_backend="dom"
            )
        if "/feed" in page.url:
            return PlatformStatus(
                self.name, "ok", "sesión válida (verificada por la URL del feed)"
            )
        return PlatformStatus(
            self.name,
            "error",
            f"no se pudo confirmar la sesión (url={page.url[:80]})",
            hint=self.login_hint(),
        )
