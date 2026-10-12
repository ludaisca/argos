"""Cliente de SearxNG: búsqueda web general (instancia propia, sin API key).

Pensado para el enriquecedor de leads: consultas baratas y en volumen contra una
instancia propia (por defecto ``https://searxng.waone.cloud``, override con
``ARGOS_SEARXNG_URL`` o ``searxng_url`` en config.yaml).
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass

import requests

from argos.config import ArgosConfig
from argos.errors import ArgosError

DEFAULT_BASE = "https://searxng.waone.cloud"
USER_AGENT = "Argos/0.1 (herramienta personal de investigacion; uso de bajo volumen)"
_MIN_INTERVAL = 1.1
_last_request = 0.0


@dataclass(frozen=True)
class SearxResult:
    title: str
    url: str
    snippet: str
    engine: str = ""


def resolve_base(config: ArgosConfig | None = None) -> str:
    env = os.environ.get("ARGOS_SEARXNG_URL")
    if env:
        return env.rstrip("/")
    if config is not None:
        stored = config.get("searxng_url")
        if stored:
            return str(stored).rstrip("/")
    return DEFAULT_BASE


def _throttle() -> None:
    global _last_request
    wait = _last_request + _MIN_INTERVAL - time.monotonic()
    if wait > 0:
        time.sleep(wait)
    _last_request = time.monotonic()


def search(
    query: str,
    *,
    base: str | None = None,
    limit: int = 8,
    language: str = "es",
    categories: str = "general",
    timeout: int = 25,
) -> list[SearxResult]:
    """Busca en la instancia de SearxNG y devuelve resultados normalizados."""
    query = (query or "").strip()
    if not query:
        return []
    endpoint = (base or DEFAULT_BASE).rstrip("/")
    _throttle()
    try:
        response = requests.get(
            f"{endpoint}/search",
            params={
                "q": query,
                "format": "json",
                "language": language,
                "categories": categories,
            },
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            timeout=timeout,
        )
    except requests.RequestException as exc:
        raise ArgosError(f"SearxNG no respondió ({endpoint}): {exc}") from exc
    if response.status_code == 403:
        raise ArgosError(
            "SearxNG rechazó el formato JSON",
            hint="habilitá `json` en search.formats del settings.yml de SearxNG",
        )
    if not response.ok:
        raise ArgosError(f"SearxNG devolvió HTTP {response.status_code}")
    try:
        data = response.json()
    except ValueError as exc:
        raise ArgosError(f"SearxNG no devolvió JSON: {exc}") from exc

    results: list[SearxResult] = []
    for item in (data.get("results") or [])[: max(1, limit)]:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "").strip()
        if not url:
            continue
        engines = item.get("engines")
        results.append(
            SearxResult(
                title=str(item.get("title") or "").strip(),
                url=url,
                snippet=str(item.get("content") or "").strip(),
                engine=", ".join(str(engine) for engine in engines)
                if isinstance(engines, list)
                else "",
            )
        )
    return results
