"""Aislamiento global y fixtures de navegador para tests que leen DOM."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "argos-home"
    home.mkdir()
    monkeypatch.setenv("ARGOS_HOME", str(home))
    return home


@pytest.fixture(scope="session")
def browser_page():
    """Página de Chromium real, con toda la red bloqueada (solo fixtures)."""
    from playwright.sync_api import Error as PlaywrightError
    from playwright.sync_api import sync_playwright

    pw = sync_playwright().start()
    try:
        browser = pw.chromium.launch(headless=True)
    except PlaywrightError as exc:
        pw.stop()
        pytest.skip(f"navegador no disponible: {exc}")
    page = browser.new_page()
    page.route("http://**", lambda route: route.abort())
    page.route("https://**", lambda route: route.abort())
    yield page
    browser.close()
    pw.stop()


@pytest.fixture
def loaded_page(browser_page) -> Callable[[str], object]:
    """Carga un fixture HTML en la página y la devuelve."""

    def load(name: str):
        html = (FIXTURES / name).read_text(encoding="utf-8")
        browser_page.set_content(html, wait_until="domcontentloaded")
        return browser_page

    return load
