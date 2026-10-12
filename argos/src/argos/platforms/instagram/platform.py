"""Probe de sesión de Instagram (dos capas: API interna → UI)."""

from __future__ import annotations

from contextlib import suppress

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Page

from argos.browser.session import BrowserSession
from argos.platforms.base import Platform, PlatformStatus
from argos.platforms.instagram.api import api_get

_BASE = "https://www.instagram.com"
_EDIT_URL = f"{_BASE}/accounts/edit/"
_LOGIN_PASSWORD_INPUT = "input[name='pass']"


class InstagramPlatform(Platform):
    name = "instagram"
    title = "Instagram"
    login_url = f"{_BASE}/"
    session_cookies = ("sessionid", "ds_user_id")
    backends = ("dom", "internal-api")

    def probe(self, session: BrowserSession, *, navigate: bool = True) -> PlatformStatus:
        page = session.page
        if navigate or not page.url.startswith(_BASE):
            session.goto(self.login_url)

        problem = session.inspect()
        if problem is not None and problem.kind != "login":
            return self._problem_status(problem)

        cookies = session.cookies()
        missing = [name for name in self.session_cookies if name not in cookies]
        if missing:
            return PlatformStatus(
                self.name,
                "needs-login",
                f"sin cookies de sesión ({', '.join(missing)})",
                hint=self.login_hint(),
            )

        api_status = self._probe_api(page)
        if api_status is not None:
            return api_status

        return self._probe_ui(session)

    # -- capas del probe ------------------------------------------------

    def _probe_api(self, page: Page) -> PlatformStatus | None:
        """Vía rápida: usuario y username. ``None`` = la API no decide (seguir a UI)."""
        result = api_get(page, "/api/v1/accounts/current_user/?edit=true")
        status = result.get("status")
        data = result.get("data")

        if status == 429:
            return PlatformStatus(
                self.name,
                "rate-limited",
                "Instagram respondió 429 a la API interna",
                hint="esperá unos minutos antes de reintentar",
            )
        if status == 200 and isinstance(data, dict):
            user = data.get("user")
            if isinstance(user, dict) and user.get("username"):
                return PlatformStatus(
                    self.name,
                    "ok",
                    f"sesión válida ({user.get('username')})",
                    active_backend="internal-api",
                )
        return None

    def _probe_ui(self, session: BrowserSession) -> PlatformStatus:
        """Verificación por UI: ``/accounts/edit/`` requiere sesión válida."""
        page = session.page
        session.goto(_EDIT_URL)
        # Dejar asentar posibles redirects del lado del cliente antes de decidir.
        with suppress(PlaywrightError):
            page.wait_for_timeout(1000)

        problem = session.inspect()
        if problem is not None:
            return self._problem_status(problem)

        try:
            password_fields = page.locator(_LOGIN_PASSWORD_INPUT).count()
        except PlaywrightError:
            password_fields = 0
        if password_fields > 0:
            return PlatformStatus(
                self.name,
                "needs-login",
                "la UI de Instagram muestra el formulario de login",
                hint=self.login_hint(),
            )
        if "/accounts/edit" in page.url:
            return PlatformStatus(
                self.name,
                "ok",
                "sesión válida (verificada en la UI)",
                active_backend="dom",
            )
        return PlatformStatus(
            self.name,
            "error",
            "no se pudo confirmar la sesión por API ni por UI "
            f"(url={page.url[:80]})",
        )
