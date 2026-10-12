"""Extracción de datos desde la UI (DOM) de Instagram.

Todo lo que se lee acá viene de lo que un humano ve: metas ``og:*`` del
documento, texto del header y la grilla de posts. Los fixtures de test son
capturas reales recortadas (``tests/fixtures/ig_profile.html`` y
``ig_post.html``) de una cuenta pública.

Notas de estructura verificadas 2026-09-30:
  - ``meta[property='og:description']`` del perfil trae contadores, nombre y
    usuario; el del post trae likes, comentarios, autor, fecha y caption.
  - La grilla usa ``a[href*='/p/']`` y ``a[href*='/reel/']``; el ``alt`` de la
    imagen contiene el caption truncado.
  - La bio vive en ``header span._ap3a`` (clase semántica de IG).
  - La fecha del post está en ``time[datetime]`` (ISO 8601).
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from playwright.sync_api import Page

from argos.models import Comment, Post, Profile, SearchHit

_COUNT_WORDS = {"k": 1_000, "m": 1_000_000, "b": 1_000_000_000}
_COUNT_RE = re.compile(r"^(?P<number>[\d.,\s]+?)\s*(?P<suffix>[KMB])?\s*$", re.IGNORECASE)
_COUNT_BEFORE_LABEL = r"(?P<number>[\d.,]+[KMB]?)\s+(?:{labels})"

_OG_PROFILE = (
    re.compile(
        r"^(?P<followers>[\d.,]+[KMB]?)\s+Followers,\s+(?P<following>[\d.,]+[KMB]?)"
        r"\s+Following,\s+(?P<posts>[\d.,]+[KMB]?)\s+Posts\s+-\s+.*?\bfrom\s+"
        r"(?P<name>.+?)\s+\(@(?P<username>[^)]+)\)",
        re.IGNORECASE | re.DOTALL,
    ),
    re.compile(
        r"^(?P<followers>[\d.,]+[KMB]?)\s+seguidores,\s+(?P<following>[\d.,]+[KMB]?)"
        r"\s+siguiendo,\s+(?P<posts>[\d.,]+[KMB]?)\s+publicaciones\s+-\s+.*?\bde\s+"
        r"(?P<name>.+?)\s+\(@(?P<username>[^)]+)\)",
        re.IGNORECASE | re.DOTALL,
    ),
)
#: Post: patrones independientes y no anclados al final (IG a veces agrega
#: puntuación después de la comilla de cierre del caption).
_POST_LIKES = re.compile(r"(?P<likes>[\d.,]+[KMB]?)\s+(?:likes?|Me gusta)", re.IGNORECASE)
_POST_COMMENTS = re.compile(
    r"(?P<comments>[\d.,]+[KMB]?)\s+(?:comments?|comentarios)", re.IGNORECASE
)
_POST_HEAD = re.compile(
    r"(?P<user>.+?)\s+(?:on|el)\s+(?P<date>[^:]+):\s*\"(?P<caption>.*)\"",
    re.IGNORECASE | re.DOTALL,
)

GRID_LINK_SELECTOR = "a[href*='/p/'], a[href*='/reel/']"
_SHORTCODE_RE = re.compile(r"/(?:p|reel)/(?P<code>[^/?#]+)")
_BARE_COUNT_RE = re.compile(r"^[\d.,]+[KMB]?$", re.IGNORECASE)
_BG_URL_RE = re.compile(r"url\([\"']?(?P<url>[^\"')]+)[\"']?\)")
_AGE_RE = re.compile(
    r"^(?P<count>\d+)\s*(?P<unit>[smhdw])"
    r"(?:\s*·\s*(?:edited|editado))?(?:\s+ago)?$",
    re.IGNORECASE,
)
_AGE_SECONDS = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}
_SKIP_COMMENT_LINE = re.compile(
    r"^(?:reply|responder|ver traducción|see translation|edited|editado|"
    r"view all \d+ repl(?:y|ies)|ver los \d+ respuestas?)$",
    re.IGNORECASE,
)

_PRIVATE_MARKERS = ("this account is private", "esta cuenta es privada")
_UNAVAILABLE_MARKERS = (
    "sorry, this page isn't available",
    "lo sentimos, esta página no está disponible",
)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def parse_count(value: str | None) -> int | None:
    """Convierte ``5,960`` / ``538K`` / ``1.2M`` / ``5.960`` a entero."""
    if value is None:
        return None
    match = _COUNT_RE.match(str(value).strip())
    if match is None:
        return None
    raw = match.group("number").strip()
    suffix = (match.group("suffix") or "").lower()
    if suffix:
        try:
            number = float(raw.replace(",", "").replace(" ", ""))
        except ValueError:
            return None
        return int(number * _COUNT_WORDS[suffix])
    digits = raw.replace(",", "").replace(".", "").replace(" ", "")
    try:
        return int(digits)
    except ValueError:
        return None


def _meta(page: Page, property_name: str) -> str | None:
    locator = page.locator(f"meta[property='{property_name}']")
    if locator.count() == 0:
        return None
    return locator.first.get_attribute("content")


def _count_from_header(text: str, *labels: str) -> int | None:
    pattern = re.compile(
        _COUNT_BEFORE_LABEL.format(labels="|".join(re.escape(label) for label in labels)),
        re.IGNORECASE,
    )
    match = pattern.search(text)
    return parse_count(match.group("number")) if match else None


def is_private_page(page: Page) -> bool:
    body = page.locator("body").inner_text().lower()
    return any(marker in body for marker in _PRIVATE_MARKERS)


def is_unavailable_page(page: Page) -> bool:
    body = page.locator("body").inner_text().lower()
    return any(marker in body for marker in _UNAVAILABLE_MARKERS)


# --------------------------------------------------------------------------- #
# Perfil
# --------------------------------------------------------------------------- #


def _extract_bio(page: Page, username: str) -> str | None:
    """Bio = primer ``span._ap3a`` del header que no sea usuario ni contador."""
    spans = page.locator("header span._ap3a")
    for index in range(min(spans.count(), 12)):
        text = (spans.nth(index).inner_text() or "").strip()
        if not text:
            continue
        if text.lstrip("@").lower() == username.lower():
            continue
        if re.fullmatch(r"[\d.,]+\s+\w+", text):
            continue
        return text
    return None


def parse_profile(page: Page, username: str) -> Profile:
    """Construye el ``Profile`` desde la pagina de perfil ya renderizada."""
    handle = username.lstrip("@")
    description = _meta(page, "og:description") or ""

    followers = following = posts_count = None
    full_name = None
    for pattern in _OG_PROFILE:
        match = pattern.match(description)
        if match is None:
            continue
        followers = parse_count(match.group("followers"))
        following = parse_count(match.group("following"))
        posts_count = parse_count(match.group("posts"))
        full_name = match.group("name").strip() or None
        break

    if followers is None or following is None or posts_count is None:
        header = page.locator("header")
        header_text = header.first.inner_text() if header.count() else ""
        followers = followers or _count_from_header(header_text, "followers", "seguidores")
        following = following or _count_from_header(header_text, "following", "siguiendo")
        posts_count = posts_count or _count_from_header(header_text, "posts", "publicaciones")

    return Profile(
        platform="instagram",
        username=handle,
        full_name=full_name,
        bio=_extract_bio(page, handle),
        followers=followers,
        following=following,
        posts_count=posts_count,
        is_private=is_private_page(page) if page.locator("body").count() else None,
        is_verified=page.locator("svg[aria-label='Verified']").count() > 0,
        profile_pic_url=_meta(page, "og:image"),
        external_url=None,
    )


# --------------------------------------------------------------------------- #
# Grilla
# --------------------------------------------------------------------------- #


_GRID_JS = """
(selector) => [...document.querySelectorAll(selector)].map((anchor) => {
  const img = anchor.querySelector('img');
  const bg = anchor.querySelector('[style*="background-image"]');
  let bgUrl = null;
  if (bg) {
    const style = bg.getAttribute('style') || '';
    const match = style.match(/url\\(["']?([^"')]+)["']?\\)/);
    if (match) bgUrl = match[1];
  }
  return {
    href: anchor.getAttribute('href') || '',
    alt: img ? (img.alt || '') : '',
    src: img ? (img.getAttribute('src') || '') : '',
    bgUrl: bgUrl,
    hasVideo: !!anchor.querySelector('video, svg[aria-label="Reel"]'),
    text: (anchor.innerText || '').trim(),
  };
})
"""


def parse_grid(
    page: Page,
    *,
    limit: int,
    author: str | None = None,
) -> list[Post]:
    """Posts visibles en una grilla (perfil, hashtag, reels, búsqueda de posts).

    El ``alt`` de la imagen trae (parte de) el caption cuando existe; en reels
    el thumbnail es un ``background-image`` y el texto del anchor suele ser el
    contador de vistas.
    """
    rows = cast(
        list[dict[str, Any]],
        page.evaluate(_GRID_JS, GRID_LINK_SELECTOR),
    )
    posts: list[Post] = []
    seen: set[str] = set()
    for row in rows:
        href = str(row.get("href") or "")
        match = _SHORTCODE_RE.search(href)
        if match is None:
            continue
        code = match.group("code")
        if code in seen:
            continue
        seen.add(code)
        url = href if href.startswith("http") else f"https://www.instagram.com{href}"

        alt = str(row.get("alt") or "").strip()
        thumbnail = str(row.get("src") or "") or str(row.get("bgUrl") or "")
        text = str(row.get("text") or "").strip()
        # La grilla de reels muestra [likes, comentarios, vistas] (una por línea);
        # otras grillas pueden mostrar solo vistas. Heurística documentada.
        counts = [
            parse_count(line)
            for line in text.splitlines()
            if _BARE_COUNT_RE.match(line.strip())
        ]
        likes = comments = views = None
        parsed_counts = [value for value in counts if value is not None]
        if len(parsed_counts) >= 3:
            likes, comments, views = parsed_counts[0], parsed_counts[1], parsed_counts[2]
        elif len(parsed_counts) == 1:
            views = parsed_counts[0]

        posts.append(
            Post(
                platform="instagram",
                id=code,
                url=url,
                caption=alt or None,
                author=author,
                media_type="video" if (row.get("hasVideo") or "/reel/" in href) else "unknown",
                thumbnail_url=thumbnail or None,
                likes=likes,
                comments=comments,
                views=views,
            )
        )
        if len(posts) >= limit:
            break
    return posts


# --------------------------------------------------------------------------- #
# Post individual
# --------------------------------------------------------------------------- #


def _time_from_datetime(page: Page) -> datetime | None:
    locator = page.locator("time[datetime]")
    if locator.count() == 0:
        return None
    value = locator.first.get_attribute("datetime")
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def parse_post_page(page: Page, *, url: str, author: str | None = None) -> Post:
    """Detalle de un post desde su página (og:description + time[datetime])."""
    description = _meta(page, "og:description") or ""

    likes: int | None = None
    comments: int | None = None
    caption: str | None = None
    parsed_author: str | None = None
    date_text: str | None = None

    head = _POST_HEAD.search(description)
    if head is not None:
        parsed_author = head.group("user").strip() or None
        date_text = head.group("date").strip() or None
        caption = head.group("caption")

    likes_match = _POST_LIKES.search(description)
    if likes_match is not None:
        likes = parse_count(likes_match.group("likes"))
    comments_match = _POST_COMMENTS.search(description)
    if comments_match is not None:
        comments = parse_count(comments_match.group("comments"))

    created_at = _time_from_datetime(page)
    if created_at is None and date_text:
        created_at = _parse_og_date(date_text)

    code_match = _SHORTCODE_RE.search(url)
    return Post(
        platform="instagram",
        id=code_match.group("code") if code_match else url,
        url=url,
        caption=(caption or "").strip() or None,
        author=(author or parsed_author),
        created_at=created_at,
        likes=likes,
        comments=comments,
        media_type="video" if "/reel/" in url else "unknown",
        thumbnail_url=_meta(page, "og:image"),
    )


_DATE_EN = re.compile(
    r"(?P<month>January|February|March|April|May|June|July|August|September|"
    r"October|November|December)\s+(?P<day>\d{1,2}),\s*(?P<year>\d{4})",
    re.IGNORECASE,
)
_MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11,
    "december": 12,
}


def _parse_og_date(value: str) -> datetime | None:
    match = _DATE_EN.search(value)
    if match is None:
        return None
    return datetime(
        int(match.group("year")),
        _MONTHS[match.group("month").lower()],
        int(match.group("day")),
        tzinfo=UTC,
    )


# --------------------------------------------------------------------------- #
# Búsqueda (panel typeahead)
# --------------------------------------------------------------------------- #

_SEARCH_JS = """
(max) => {
  const isResult = (href) =>
    /^\\/[A-Za-z0-9._]+\\/?$/.test(href) ||
    href.startsWith('/explore/tags/') ||
    href.startsWith('/explore/locations/');
  const blocked = /^\\/(popular|legal|web|accounts|direct|explore\\/(?!tags|locations))/;
  const out = [];
  const seen = new Set();
  for (const anchor of document.querySelectorAll('a[href]')) {
    const href = anchor.getAttribute('href') || '';
    if (!isResult(href) || blocked.test(href)) continue;
    if (anchor.closest('footer')) continue;
    if (seen.has(href)) continue;
    seen.add(href);
    const text = (anchor.innerText || '').replace(/\\n/g, ' ').trim();
    if (!text) continue;
    out.push({href, text});
    if (out.length >= max) break;
  }
  return out;
}
"""


def _split_search_text(
    text: str, username: str | None = None
) -> tuple[str | None, int | None]:
    """``"nasa NASA • 104M followers"`` -> ``("NASA", 104000000)``.

    El panel muestra el handle seguido del nombre (separados por espacio o
    ``|`` según la variante de la UI); el nombre puede tener espacios.
    """
    followers: int | None = None
    match = re.search(r"•\s*([\d.,]+[KMB]?)\s+followers?", text, re.IGNORECASE)
    if match is not None:
        followers = parse_count(match.group(1))
        text = text[: match.start()]
    tokens = text.replace("|", " ").split()
    if not tokens:
        return None, followers
    if (username and tokens[0].lower() == username.lower()) or len(tokens) > 1:
        tokens = tokens[1:]
    else:
        return None, followers
    name = " ".join(tokens).strip(" •") or None
    return name, followers


def parse_search_panel(page: Page, limit: int) -> list[SearchHit]:
    """Resultados del panel de búsqueda (usuarios, hashtags, lugares)."""
    rows = cast(list[dict[str, Any]], page.evaluate(_SEARCH_JS, limit * 2))
    hits: list[SearchHit] = []
    for row in rows:
        href = str(row.get("href") or "")
        text = str(row.get("text") or "")
        if href.startswith("/explore/tags/"):
            tag = href.rstrip("/").split("/")[-1]
            hits.append(
                SearchHit(
                    type="tag",
                    username=tag,
                    name=text.strip(" #") or tag,
                    url=f"https://www.instagram.com{href}",
                )
            )
        elif href.startswith("/explore/locations/"):
            hits.append(
                SearchHit(
                    type="place",
                    name=text or href,
                    url=f"https://www.instagram.com{href}",
                )
            )
        else:
            username = href.strip("/").split("/")[-1]
            name, followers = _split_search_text(text, username)
            hits.append(
                SearchHit(
                    type="user",
                    username=username,
                    name=name or username,
                    url=f"https://www.instagram.com/{username}/",
                    followers=followers,
                )
            )
        if len(hits) >= limit:
            break
    return hits


# --------------------------------------------------------------------------- #
# Comentarios
# --------------------------------------------------------------------------- #

_COMMENTS_JS = """
(max) => {
  const isAuthorLink = (href) =>
    /^\\/[A-Za-z0-9._]+\\/?$/.test(href) &&
    !/^\\/(p|reel|explore|accounts|stories|legal|web|popular|direct)\\b/.test(href);
  const isAge = (line) =>
    /^\\d+\\s*[smhdw](\\s*·\\s*(edited|editado))?(\\s+ago)?$/i.test(line);
  const isNoise = (line) =>
    /^(reply|responder|ver traducción|see translation|edited|editado|view all \\d+ repl)/i
      .test(line);
  const out = [];
  const seen = new Set();
  for (const link of document.querySelectorAll("a[href*='/c/']")) {
    const permalink = link.getAttribute('href') || '';
    if (seen.has(permalink)) continue;
    let node = link;
    let item = null;
    let authorLink = null;
    let authorText = '';
    for (let depth = 0; depth < 8 && node; depth++) {
      node = node.parentElement;
      if (!node) break;
      // no cruzar hacia comentarios vecinos
      if (node.querySelectorAll("a[href*='/c/']").length > 1) break;
      const found = [...node.querySelectorAll('a[href]')]
        .find(a => isAuthorLink(a.getAttribute('href') || ''));
      const candidateText = found ? (found.innerText || '').trim() : '';
      const candidateHandle = found
        ? (found.getAttribute('href') || '').replace(/\\//g, '')
        : '';
      const lines = (node.innerText || '').split('\\n').map(s => s.trim()).filter(Boolean);
      const body = lines.filter(line =>
        line !== candidateText &&
        line.toLowerCase() !== candidateHandle.toLowerCase() &&
        !isAge(line) && !isNoise(line));
      if (found && body.length) {
        item = node;
        authorLink = found;
        authorText = candidateText;
        break;
      }
    }
    if (!item) continue;
    seen.add(permalink);
    out.push({
      permalink,
      author: authorLink
        ? (authorLink.getAttribute('href') || '').replace(/\\//g, '')
        : null,
      authorText,
      lines: (item.innerText || '').split('\\n').map(s => s.trim()).filter(Boolean).slice(0, 15),
    });
    if (out.length >= max) break;
  }
  return out;
}
"""


def _age_to_datetime(age_text: str | None) -> datetime | None:
    match = _AGE_RE.match(age_text or "")
    if match is None:
        return None
    seconds = _AGE_SECONDS[match.group("unit").lower()] * int(match.group("count"))
    return datetime.now(UTC) - timedelta(seconds=seconds)


def parse_comments(page: Page, *, post_url: str, limit: int) -> list[Comment]:
    """Comentarios visibles de un post (autor, texto y antigüedad relativa)."""
    rows = cast(list[dict[str, Any]], page.evaluate(_COMMENTS_JS, limit * 3))
    comments: list[Comment] = []
    for row in rows:
        author = row.get("author")
        author_value = str(author) if author else None
        author_text = str(row.get("authorText") or "").strip()
        age_text: str | None = None
        text_lines: list[str] = []
        for line in row.get("lines", []):
            stripped = str(line).strip()
            if not stripped:
                continue
            if author_value and stripped.lstrip("@").lower() == author_value.lower():
                continue
            if author_text and stripped == author_text:
                continue
            if _SKIP_COMMENT_LINE.match(stripped):
                continue
            if age_text is None and _AGE_RE.match(stripped):
                age_text = stripped
                continue
            text_lines.append(stripped)
        text = "\n".join(text_lines).strip()
        if not text:
            continue
        permalink = str(row.get("permalink") or "")
        id_match = re.search(r"/c/(\d+)", permalink)
        comments.append(
            Comment(
                platform="instagram",
                id=id_match.group(1) if id_match else permalink,
                url=(
                    permalink
                    if permalink.startswith("http")
                    else f"https://www.instagram.com{permalink}"
                ),
                post_url=post_url,
                author=author_value,
                text=text,
                age_text=age_text,
                created_at=_age_to_datetime(age_text),
            )
        )
        if len(comments) >= limit:
            break
    return comments
