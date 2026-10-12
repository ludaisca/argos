"""Probe de YouTube (no requiere login: el contenido es público)."""

from __future__ import annotations

from playwright.sync_api import Error as PlaywrightError

from argos.browser.session import BrowserSession
from argos.platforms.base import Platform, PlatformStatus

_BASE = "https://www.youtube.com"


class YouTubePlatform(Platform):
    name = "youtube"
    title = "YouTube"
    login_url = f"{_BASE}/"
    session_cookies = ()
    backends = ("dom", "initial-data")

    def probe(self, session: BrowserSession, *, navigate: bool = True) -> PlatformStatus:
        page = session.page
        if navigate or not page.url.startswith(_BASE):
            session.goto(self.login_url)

        try:
            page.wait_for_selector("ytd-app", timeout=15000)
        except PlaywrightError:
            return PlatformStatus(
                self.name, "error", "YouTube no cargó la app (¿bloqueo de red?)"
            )

        problem = session.inspect()
        if problem is not None and problem.kind not in ("login",):
            return self._problem_status(problem)

        try:
            logged = (
                page.locator("#avatar-btn").count() > 0
                or page.locator("button[aria-label*='Google Account']").count() > 0
                or page.locator("button[aria-label*='Cuenta de Google']").count() > 0
            )
        except PlaywrightError:
            logged = False

        if logged:
            return PlatformStatus(
                self.name,
                "ok",
                "con sesión de Google (opcional; el scraping es público)",
                active_backend="dom",
            )
        return PlatformStatus(
            self.name,
            "ok",
            "modo invitado (YouTube público no requiere login)",
            active_backend="dom",
        )
