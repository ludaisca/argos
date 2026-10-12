"""Extracción de datos desde la UI (DOM) de Facebook.

Estructura verificada 2026-09-30 (interfaz en español):
  - El header expone nombre y "N mill. seguidores • M seguidos" como texto.
  - Cada post es un DIV **sin rol** que contiene texto, antigüedad relativa
    ("hace 3 horas") y los contadores (reacciones/comentarios/compartidos) como
    líneas sueltas antes de "Ver más comentarios". Los comentarios SÍ son
    ``div[role=article]``: por eso el post no se detecta por rol.
  - Los resultados de búsqueda son ``div[role=article]`` con el texto
    "Nombre | Categoría · N seguidores · … | bio".

Los fixtures de test son recortes reales (``tests/fixtures/fb_page.html`` y
``fb_search.html``).
"""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from playwright.sync_api import Page

from argos.models import Post, Profile, SearchHit

_AGE_LINE_RE = re.compile(
    r"^(?:hace\s+.+|\d+\s*(?:min|minutos?|h|horas?|d|d[ií]as?|sem|semanas?|a|años?)\b.*"
    r"|\d+\s*(?:minutes?|hours?|days?|weeks?|years?)\s+ago|yesterday|ayer)$",
    re.IGNORECASE,
)
_REL_AGE_RE = re.compile(
    r"hace\s+(?P<count>\d+)\s*(?P<unit>min|minutos?|h|horas?|d|d[ií]as?|sem|semanas?|a|años?)",
    re.IGNORECASE,
)
_REL_AGE_EN_RE = re.compile(
    r"(?P<count>\d+)\s*(?P<unit>minutes?|hours?|days?|weeks?|years?)\s+ago",
    re.IGNORECASE,
)
_AGE_SECONDS = {
    "min": 60, "minuto": 60, "minutos": 60,
    "h": 3600, "hora": 3600, "horas": 3600,
    "d": 86400, "dia": 86400, "día": 86400, "dias": 86400, "días": 86400,
    "sem": 604800, "semana": 604800, "semanas": 604800,
    "a": 31536000, "año": 31536000, "años": 31536000,
    "minute": 60, "minutes": 60,
    "hour": 3600, "hours": 3600,
    "day": 86400, "days": 86400,
    "week": 604800, "weeks": 604800,
    "year": 31536000, "years": 31536000,
}
_NOISE_LINES = {
    "me gusta", "comentar", "compartir", "like", "comment", "share",
    "ver más", "see more", "seguir", "follow", "responder", "reply",
    "ver original", "see original", "calificar esta traducción",
    "rate this translation", "·",
}
_CARD_MARKER = re.compile(r"(?:ver más comentarios|view more comments)", re.IGNORECASE)

_CARDS_JS = """
(max) => {
  // Los posts muestran "hace 3 horas"; los comentarios muestran "3 min" a secas
  // (formato más corto): exigimos el formato de post para no confundirlos.
  const isAge = (line) =>
    /^hace\\s+.+$/i.test(line) ||
    /^(ayer|yesterday)$/i.test(line) ||
    /^\\d+\\s*(minutes?|hours?|days?|weeks?|years?)\\s+ago$/i.test(line);
  const isCard = (el) => {
    const t = el.innerText || '';
    return t.length >= 80 && /ver más comentarios|view more comments/i.test(t);
  };
  const out = [];
  const seen = new Set();
  for (const el of document.querySelectorAll('span, a, abbr')) {
    const text = (el.innerText || '').trim();
    if (!isAge(text)) continue;
    let node = el;
    let card = null;
    for (let i = 0; i < 12 && node; i++) {
      node = node.parentElement;
      if (!node) break;
      if (isCard(node)) { card = node; break; }
    }
    if (!card || seen.has(card)) continue;
    seen.add(card);
    out.push((card.innerText || '').split('\\n').map(s => s.trim()).filter(Boolean));
    if (out.length >= max) break;
  }
  return out;
}
"""

_SEARCH_JS = """
(max) => [...document.querySelectorAll('div[role=article]')].slice(0, max).map(article => ({
  lines: (article.innerText || '').split('\\n')
    .map(s => s.replace(/\\ufeff/g, '').trim()).filter(Boolean),
  anchors: [...article.querySelectorAll('a[href]')].map(a => a.getAttribute('href') || ''),
}))
"""


# --------------------------------------------------------------------------- #
# Números
# --------------------------------------------------------------------------- #


def parse_count_es(text: str | None) -> int | None:
    """``28 mill.`` → 28 000 000 · ``279 mil`` → 279 000 · ``1,7 mill.`` → 1 700 000.

    También acepta enteros con separadores (``5,960`` / ``5.960``) y sufijos
    ingleses (``1.2M``).
    """
    if not text:
        return None
    cleaned = str(text).strip().replace("\xa0", " ")
    match = re.match(r"^(?P<num>[\d.,]+)\s*(?P<unit>[A-Za-z.]*)$", cleaned)
    if match is None:
        return None
    raw = match.group("num")
    unit = (match.group("unit") or "").strip().rstrip(".").lower()
    if unit in ("mil", "k"):
        factor = 1_000
    elif unit in ("mill", "m"):
        factor = 1_000_000
    elif unit in ("b",):
        factor = 1_000_000_000
    elif unit == "":
        digits = raw.replace(",", "").replace(".", "").replace(" ", "")
        try:
            return int(digits)
        except ValueError:
            return None
    else:
        return None
    if "," in raw and "." in raw:
        normalized = raw.replace(".", "").replace(",", ".")
    elif "," in raw:
        normalized = raw.replace(",", ".")
    else:
        normalized = raw
    try:
        return int(float(normalized) * factor)
    except ValueError:
        return None


def parse_fb_age(age_text: str | None) -> datetime | None:
    """Antigüedad relativa de FB → datetime aproximado (UTC)."""
    if not age_text:
        return None
    lowered = age_text.strip().lower()
    if lowered in ("ayer", "yesterday"):
        return datetime.now(UTC) - timedelta(days=1)
    match = _REL_AGE_RE.search(lowered) or _REL_AGE_EN_RE.search(lowered)
    if match is None:
        return None
    unit = match.group("unit").lower()
    seconds = _AGE_SECONDS.get(unit)
    if seconds is None:
        return None
    return datetime.now(UTC) - timedelta(seconds=seconds * int(match.group("count")))


# --------------------------------------------------------------------------- #
# Perfil de página
# --------------------------------------------------------------------------- #


def parse_profile(page: Page, slug: str) -> Profile:
    """Datos de la página desde el header (nombre y contadores como texto)."""
    lines = [
        line.strip().replace("\ufeff", "")
        for line in page.locator("body").inner_text().splitlines()
    ]
    lines = [line for line in lines if line]

    followers: int | None = None
    following: int | None = None
    name: str | None = None
    for index, line in enumerate(lines):
        lowered = line.lower()
        if "seguidores" not in lowered or len(line) > 90:
            continue
        match = re.search(
            r"(?P<value>[\d.,\s\xa0]*(?:mil|mill\.?|K|M)?)\s*seguidores", line, re.IGNORECASE
        )
        if match:
            followers = parse_count_es(match.group("value"))
        match2 = re.search(
            r"(?P<value>[\d.,\s\xa0]*(?:mil|mill\.?|K|M)?)\s*seguidos", line, re.IGNORECASE
        )
        if match2:
            following = parse_count_es(match2.group("value"))
        if index > 0:
            name = lines[index - 1] or None
        break

    return Profile(
        platform="facebook",
        username=slug,
        full_name=name,
        followers=followers,
        following=following,
    )


# --------------------------------------------------------------------------- #
# Posts
# --------------------------------------------------------------------------- #


def _parse_card(lines: list[str], *, author_hint: str | None, page_url: str) -> Post | None:
    age_index = next(
        (index for index, line in enumerate(lines) if _AGE_LINE_RE.match(line)), None
    )
    if age_index is None or age_index == 0:
        return None

    author = lines[age_index - 1].strip().replace("\ufeff", "") or author_hint
    age_text = lines[age_index]

    body_lines: list[str] = []
    numbers: list[int] = []
    for line in lines[age_index + 1 :]:
        lowered = line.lower()
        if _CARD_MARKER.search(line):
            break
        if lowered in _NOISE_LINES:
            continue
        if line.startswith("·"):
            cleaned = line.lstrip("· ").strip()
            if not cleaned or cleaned.lower() in _NOISE_LINES:
                continue
            body_lines.append(cleaned)
            continue
        if re.fullmatch(r"[\d.,]+", line):
            value = parse_count_es(line)
            if value is not None:
                numbers.append(value)
            continue
        body_lines.append(line)

    text = "\n".join(body_lines).strip()
    # Ruido típico del feed: botón "Ver más", duración de video y CTAs adjuntas.
    text = re.sub(r"\b(?:Ver|See) más\b", " ", text)
    text = re.sub(r"\b\d{1,2}:\d{2}\s*/\s*\d{1,2}:\d{2}\b", " ", text)
    text = re.sub(r"[ \t]{2,}", " ", text).strip()
    if not text:
        return None

    digest = hashlib.sha1(
        f"{author or ''}|{text[:200]}".encode()
    ).hexdigest()[:16]
    return Post(
        platform="facebook",
        id=digest,
        url=page_url,
        caption=text,
        author=author,
        created_at=parse_fb_age(age_text),
        likes=numbers[0] if numbers else None,
        comments=numbers[1] if len(numbers) > 1 else None,
        shares=numbers[2] if len(numbers) > 2 else None,
    )


def parse_posts(
    page: Page,
    *,
    limit: int,
    author_hint: str | None = None,
    page_url: str = "",
) -> list[Post]:
    """Posts visibles en la página/feed (tarjetas detectadas por antigüedad)."""
    cards = cast(list[list[str]], page.evaluate(_CARDS_JS, limit * 2))
    posts: list[Post] = []
    seen: set[str] = set()
    for lines in cards:
        post = _parse_card(list(lines), author_hint=author_hint, page_url=page_url)
        if post is None or post.id in seen:
            continue
        seen.add(post.id)
        posts.append(post)
        if len(posts) >= limit:
            break
    return posts


# --------------------------------------------------------------------------- #
# Búsqueda
# --------------------------------------------------------------------------- #

_KIND_TO_TYPE = {"pages": "page", "groups": "group", "people": "person"}


def parse_search_results(
    page: Page,
    *,
    kind: str = "pages",
    limit: int = 12,
) -> list[SearchHit]:
    """Resultados de ``/search/{pages|groups|people}/``."""
    rows = cast(list[dict[str, Any]], page.evaluate(_SEARCH_JS, limit * 2))
    hits: list[SearchHit] = []
    for row in rows:
        lines = [str(line) for line in row.get("lines", [])]
        if not lines:
            continue
        name = lines[0].strip()
        if not name:
            continue
        followers: int | None = None
        if len(lines) > 1:
            match = re.search(
                r"([\d.,]+\s*(?:mil|mill\.?|K|M)?)\s*seguidores",
                lines[1],
                re.IGNORECASE,
            )
            if match:
                followers = parse_count_es(match.group(1))
        url = ""
        username: str | None = None
        for anchor in row.get("anchors", []):
            href = str(anchor)
            base = href.split("?")[0]
            if base.endswith("/profile.php"):
                match_id = re.search(r"[?&]id=(\d+)", href)
                if match_id:
                    url = f"{base}?id={match_id.group(1)}"
                    username = match_id.group(1)
                    break
                continue
            if re.match(r"^https?://[^/]*facebook\.com/[^/]+/?$", base):
                url = base.rstrip("/") + "/"
                username = url.rstrip("/").rsplit("/", 1)[-1]
                break
        hits.append(
            SearchHit(
                platform="facebook",
                type=cast(Any, _KIND_TO_TYPE.get(kind, "page")),
                username=username,
                name=name,
                url=url or "https://www.facebook.com/",
                followers=followers,
            )
        )
        if len(hits) >= limit:
            break
    return hits
