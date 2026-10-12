"""Probe de sesión de Facebook (verificación en /me)."""

from __future__ import annotations

from playwright.sync_api import Error as PlaywrightError

from argos.browser.session import BrowserSession
from argos.platforms.base import Platform, PlatformStatus

_ME_URL = "https://www.facebook.com/me"
_PASSWORD_INPUT = "input[name='pass']"


class FacebookPlatform(Platform):
    name = "facebook"
    title = "Facebook"
    login_url = "https://www.facebook.com/"
    session_cookies = ("c_user", "xs")
    backends = ("dom",)

    def probe(self, session: BrowserSession, *, navigate: bool = True) -> PlatformStatus:
        page = session.page
        cookies = session.cookies()
        missing = [name for name in self.session_cookies if name not in cookies]
        if missing:
            return PlatformStatus(
                self.name,
                "needs-login",
                f"sin cookies de sesión ({', '.join(missing)})",
                hint=self.login_hint(),
            )

        if navigate:
            session.goto(_ME_URL)

        problem = session.inspect()
        if problem is not None and problem.kind != "login":
            return self._problem_status(problem)

        try:
            password_fields = page.locator(_PASSWORD_INPUT).count()
        except PlaywrightError:
            password_fields = 0
        if password_fields > 0:
            return PlatformStatus(
                self.name,
                "needs-login",
                "la página muestra el formulario de login",
                hint=self.login_hint(),
            )
        if problem is not None:
            return PlatformStatus(
                self.name,
                "needs-login",
                "redirigido a la pantalla de login",
                hint=self.login_hint(),
            )

        detail = (
            "sesión válida (verificada en /me)"
            if navigate
            else "cookies de sesión presentes"
        )
        return PlatformStatus(self.name, "ok", detail, active_backend="dom")
