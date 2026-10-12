"""Smoke e2e: contexto persistente real de Playwright y evidencia.

Se saltea solo si no hay navegador instalado (ni Chrome ni Chromium).
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.e2e


def test_persistent_context_smoke(isolated_home: Path) -> None:
    from playwright.sync_api import Error as PlaywrightError

    from argos.browser.session import BrowserSession
    from argos.config import ArgosConfig

    config = ArgosConfig.load()
    try:
        with BrowserSession("instagram", config, headless=True) as session:
            session.page.goto(
                "data:text/html,<title>Argos</title><h1>hola</h1>",
                wait_until="domcontentloaded",
            )
            assert session.page.title() == "Argos"
            assert session.cookies() == {}

            evidence = session.save_evidence("smoke")
            assert (evidence / "page.png").exists()
            assert (evidence / "page.html").exists()
            assert (evidence / "meta.json").exists()
    except PlaywrightError as exc:
        pytest.skip(f"navegador no disponible: {exc}")

    assert config.profile_dir("instagram").is_dir()
