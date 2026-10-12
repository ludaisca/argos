"""Lanzamiento de Chrome/Chromium con contexto persistente."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path
from typing import Any

from playwright.sync_api import BrowserContext, Playwright
from playwright.sync_api import Error as PlaywrightError

from argos.config import ArgosConfig
from argos.private_fs import make_private_dir

_ANTI_AUTOMATION_ARGS = ("--disable-blink-features=AutomationControlled",)
_BASE_ARGS = ("--no-first-run", "--no-default-browser-check")


def detect_chrome() -> Path | None:
    """Ruta al Chrome instalado, si existe (mejor huella que el Chromium bundled)."""
    candidates: list[Path] = []
    if sys.platform == "win32":
        for env in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
            base = os.environ.get(env)
            if base:
                candidates.append(
                    Path(base) / "Google" / "Chrome" / "Application" / "chrome.exe"
                )
    elif sys.platform == "darwin":
        candidates.append(
            Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
        )
    else:
        for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser"):
            found = shutil.which(name)
            if found:
                candidates.append(Path(found))
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def launch_context(
    pw: Playwright,
    config: ArgosConfig,
    platform: str,
    *,
    headless: bool | None = None,
    proxy: str | None = None,
) -> BrowserContext:
    """Abre (o reutiliza) el contexto persistente de la plataforma.

    Intenta primero con el Chrome instalado y cae al Chromium de Playwright si
    no está disponible. ``headless=None`` usa el valor de la configuración.
    """
    profile_dir = make_private_dir(config.profile_dir(platform))
    effective_headless = config.headless if headless is None else headless
    effective_proxy = proxy if proxy is not None else config.proxy

    kwargs: dict[str, Any] = {
        "user_data_dir": str(profile_dir),
        "headless": effective_headless,
        "viewport": {"width": 1440, "height": 900},
        "args": [*_ANTI_AUTOMATION_ARGS, *_BASE_ARGS],
        "accept_downloads": False,
        "ignore_https_errors": False,
    }
    if config.locale:
        kwargs["locale"] = config.locale
    if config.timezone_id:
        kwargs["timezone_id"] = config.timezone_id
    if effective_proxy:
        kwargs["proxy"] = {"server": effective_proxy}

    if detect_chrome() is not None:
        try:
            return pw.chromium.launch_persistent_context(channel="chrome", **kwargs)
        except PlaywrightError:
            pass  # Chrome presente pero no lanzable: seguir con el bundled
    return pw.chromium.launch_persistent_context(**kwargs)
