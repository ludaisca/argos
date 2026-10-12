"""Chequeo de entorno y de sesiones: la base del comando ``argos doctor``."""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from playwright.sync_api import Error as PlaywrightError

from argos.browser.launch import detect_chrome
from argos.browser.session import BrowserSession
from argos.config import ArgosConfig
from argos.errors import ArgosError
from argos.platforms import get_platform, platform_names
from argos.platforms.base import PlatformStatus


def browser_readiness() -> tuple[bool, str]:
    """¿Hay un navegador lanzable? Devuelve (listo, descripción/hint)."""
    chrome = detect_chrome()
    if chrome is not None:
        return True, f"Chrome instalado ({chrome})"
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return False, "Playwright no está instalado: `pip install playwright`"
    try:
        with sync_playwright() as pw:
            executable = Path(pw.chromium.executable_path)
    except Exception as exc:  # noqa: BLE001 - doctor no debe caerse por esto
        return False, f"no se pudo verificar Chromium: {exc}"
    if executable.exists():
        return True, "Chromium de Playwright"
    return False, "navegador no instalado: `python -m playwright install chromium`"


def collect(
    config: ArgosConfig,
    *,
    platforms: Sequence[str] | None = None,
    headless: bool = True,
) -> dict[str, Any]:
    """Estado de cada plataforma. Un canal roto no puede tumbar el reporte."""
    names = tuple(platforms) if platforms else platform_names()
    ready, browser_detail = browser_readiness()

    results: dict[str, dict[str, str | None]] = {}
    for name in names:
        platform = get_platform(name)
        if not ready:
            status = PlatformStatus(
                name,
                "off",
                browser_detail,
                hint="instalá el navegador con `python -m playwright install chromium`",
            )
        else:
            try:
                with BrowserSession(name, config, headless=headless) as session:
                    status = platform.probe(session, navigate=True)
            except PlaywrightError as exc:
                status = PlatformStatus(name, "error", f"falló el navegador: {exc}")
            except ArgosError as exc:
                status = PlatformStatus(name, "error", str(exc), hint=exc.hint)
            except Exception as exc:  # noqa: BLE001 - doctor sobrevive a todo
                status = PlatformStatus(name, "error", f"fallo inesperado: {exc}")
        entry = status.as_dict()
        entry["checked_at"] = dt.datetime.now(dt.UTC).isoformat(timespec="seconds")
        results[name] = entry

    return {
        "generated_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "browser": {"ready": ready, "detail": browser_detail},
        "platforms": results,
    }
