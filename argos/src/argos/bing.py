"""Búsqueda web de respaldo: Bing directo (sin login ni API key).

Se usa cuando la instancia de SearxNG devuelve vacío (p. ej. cuando su motor de
Google se satura). Devuelve ``SearxResult`` para que el pipeline sea idéntico.

Notas de cuidado:
- Throttle propio (``_MIN_INTERVAL``) además del throttle de SearxNG.
- Sesgo a México vía ``mkt=es-MX``/``cc=MX`` (los resultados se filtran igual).
- User-Agent de navegador real (Bing sirve HTML a requests normales).
"""

from __future__ import annotations

import base64
import html as html_mod
import re
import time
from urllib.parse import parse_qs, urlparse

import requests

from argos.errors import ArgosError
from argos.searxng import SearxResult

BING_URL = "https://www.bing.com/search"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
_MIN_INTERVAL = 2.0
_last_request = 0.0

_BLOCK_SPLIT = re.compile(r'<li class="b_algo".*?(?=<li class="b_algo"|</ol>|$)', re.S)
_LINK_RE = re.compile(r'<h2[^>]*>\s*<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', re.S)
_SNIP_RE = re.compile(r"<p[^>]*>(.*?)</p>", re.S)
_TAG_RE = re.compile(r"<[^>]+>")


def _throttle() -> None:
    global _last_request
    wait = _last_request + _MIN_INTERVAL - time.monotonic()
    if wait > 0:
        time.sleep(wait)
    _last_request = time.monotonic()


def _decode_bing_url(url: str) -> str:
    """Desenvuelve los redirects ``bing.com/ck/a?...&u=a1<base64>``."""
    if "bing.com/ck/a" not in url:
        return url
    params = parse_qs(urlparse(url).query)
    raw = (params.get("u") or [""])[0]
    if not raw.startswith("a1"):
        return url
    payload = raw[2:]
    padded = payload + "=" * (-len(payload) % 4)
    try:
        decoded = base64.urlsafe_b64decode(padded).decode("utf-8", "replace")
    except (ValueError, TypeError):
        return url
    return decoded if decoded.startswith("http") else url


def _clean(fragment: str) -> str:
    text = _TAG_RE.sub(" ", fragment)
    return re.sub(r"\s+", " ", html_mod.unescape(text)).strip()


def search(query: str, *, limit: int = 8, timeout: int = 25) -> list[SearxResult]:
    """Busca en Bing (es-MX) y devuelve resultados normalizados."""
    query = (query or "").strip()
    if not query:
        return []
    _throttle()
    try:
        response = requests.get(
            BING_URL,
            params={"q": query, "mkt": "es-MX", "setlang": "es", "cc": "MX"},
            headers={
                "User-Agent": USER_AGENT,
                "Accept-Language": "es-MX,es;q=0.9",
                "Accept": "text/html,application/xhtml+xml",
            },
            timeout=timeout,
        )
    except requests.RequestException as exc:
        raise ArgosError(f"Bing no respondió: {exc}") from exc
    if not response.ok:
        raise ArgosError(f"Bing devolvió HTTP {response.status_code}")
    results: list[SearxResult] = []
    for block in _BLOCK_SPLIT.findall(response.text):
        link = _LINK_RE.search(block)
        if not link:
            continue
        url = _decode_bing_url(html_mod.unescape(link.group(1)).strip())
        if not url.startswith("http"):
            continue
        title = _clean(link.group(2))
        snippet_match = _SNIP_RE.search(block)
        snippet = _clean(snippet_match.group(1)) if snippet_match else ""
        results.append(SearxResult(title=title, url=url, snippet=snippet, engine="bing"))
        if len(results) >= max(1, limit):
            break
    return results
