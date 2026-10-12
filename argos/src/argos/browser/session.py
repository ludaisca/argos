"""Sesión de navegador persistente por plataforma."""

from __future__ import annotations

import datetime as dt
import json
import re
from contextlib import suppress
from pathlib import Path
from typing import Literal

from playwright.sync_api import (
    BrowserContext,
    Page,
    Playwright,
    sync_playwright,
)
from playwright.sync_api import (
    Error as PlaywrightError,
)

from argos.browser.checkpoints import Problem, detect_problem, read_page_text
from argos.browser.launch import launch_context
from argos.config import ArgosConfig
from argos.cookies import inject_if_needed
from argos.errors import CheckpointError, LoginRequiredError, RateLimitedError
from argos.private_fs import PrivatePathError, atomic_write_private_text, make_private_dir

WaitUntil = Literal["commit", "domcontentloaded", "load", "networkidle"]

_NAV_TIMEOUT_MS = 45_000
_ACTION_TIMEOUT_MS = 20_000


class BrowserSession:
    """Context manager del contexto persistente de una plataforma.

    Ejemplo:
        with BrowserSession("instagram") as session:
            session.goto("https://www.instagram.com/")
            session.raise_if_problem()
    """

    def __init__(
        self,
        platform: str,
        config: ArgosConfig | None = None,
        *,
        headless: bool | None = None,
        proxy: str | None = None,
    ) -> None:
        self.platform = platform
        self.config = config or ArgosConfig.load()
        self._headless = headless
        self._proxy = proxy
        self._playwright: Playwright | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None

    # -- ciclo de vida -------------------------------------------------

    def __enter__(self) -> BrowserSession:
        pw = sync_playwright().start()
        self._playwright = pw
        try:
            context = launch_context(
                pw,
                self.config,
                self.platform,
                headless=self._headless,
                proxy=self._proxy,
            )
        except BaseException:
            pw.stop()
            self._playwright = None
            raise
        self._context = context
        context.set_default_timeout(_ACTION_TIMEOUT_MS)
        context.set_default_navigation_timeout(_NAV_TIMEOUT_MS)
        with suppress(PlaywrightError):
            inject_if_needed(context, self.platform, self.config)
        self._page = context.pages[0] if context.pages else context.new_page()
        return self

    def __exit__(self, *exc_info: object) -> None:
        context, pw = self._context, self._playwright
        self._context = None
        self._page = None
        self._playwright = None
        if context is not None:
            with suppress(PlaywrightError):
                context.close()
        if pw is not None:
            with suppress(PlaywrightError):
                pw.stop()

    # -- acceso --------------------------------------------------------

    @property
    def context(self) -> BrowserContext:
        if self._context is None:
            raise RuntimeError("la sesión no está iniciada (usar como context manager)")
        return self._context

    @property
    def page(self) -> Page:
        if self._page is None or self._page.is_closed():
            if self._context is None:
                raise RuntimeError("la sesión no está iniciada (usar como context manager)")
            self._page = self._context.new_page()
        return self._page

    # -- operaciones ---------------------------------------------------

    def goto(self, url: str, *, wait_until: WaitUntil = "domcontentloaded") -> None:
        self.page.goto(url, wait_until=wait_until)

    def cookies(self) -> dict[str, str]:
        jar: dict[str, str] = {}
        for cookie in self.context.cookies():
            name = cookie.get("name")
            value = cookie.get("value")
            if isinstance(name, str) and isinstance(value, str):
                jar[name] = value
        return jar

    def has_cookies(self, names: tuple[str, ...]) -> bool:
        jar = self.cookies()
        return all(name in jar for name in names)

    def inspect(self) -> Problem | None:
        """Problema de la página actual (login-wall/checkpoint/rate-limit)."""
        page = self.page
        try:
            title = page.title()
        except PlaywrightError:
            title = ""
        return detect_problem(self.platform, page.url, title, read_page_text(page))

    # -- evidencia y errores -------------------------------------------

    def save_evidence(self, tag: str, problem: Problem | None = None) -> Path:
        """Guarda screenshot + HTML + meta en ``~/.argos/debug/``. Nunca lanza."""
        stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        slug = re.sub(r"[^A-Za-z0-9._-]+", "-", tag).strip("-") or "evidence"
        target = self.config.debug_dir() / f"{stamp}-{slug}"
        try:
            make_private_dir(target)
        except (OSError, PrivatePathError):
            return target

        page_url: str | None = None
        with suppress(PlaywrightError):
            page_url = self.page.url

        with suppress(PlaywrightError, OSError):
            self.page.screenshot(path=str(target / "page.png"), full_page=True)
        with suppress(PlaywrightError, OSError, PrivatePathError):
            atomic_write_private_text(target / "page.html", self.page.content())
        meta = {
            "platform": self.platform,
            "url": page_url,
            "problem": problem.kind if problem is not None else None,
            "detail": problem.detail if problem is not None else None,
            "saved_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        }
        with suppress(OSError, PrivatePathError):
            atomic_write_private_text(
                target / "meta.json",
                json.dumps(meta, ensure_ascii=False, indent=2),
            )
        return target

    def raise_if_problem(self, problem: Problem | None = None) -> None:
        """Convierte el problema detectado en la excepción tipada correspondiente."""
        found = problem if problem is not None else self.inspect()
        if found is None:
            return
        if found.kind == "login":
            raise LoginRequiredError(
                f"{self.platform}: {found.detail}",
                hint=f"ejecutá `argos login {self.platform}`",
            )
        if found.kind == "checkpoint":
            evidence = self.save_evidence("checkpoint", found)
            raise CheckpointError(
                f"{self.platform}: {found.detail}",
                hint="resolvé la verificación en la ventana del navegador y reintentá",
                evidence=str(evidence),
            )
        evidence = self.save_evidence("rate-limit", found)
        raise RateLimitedError(
            f"{self.platform}: {found.detail}",
            hint="esperá unos minutos antes de reintentar",
            evidence=str(evidence),
        )
