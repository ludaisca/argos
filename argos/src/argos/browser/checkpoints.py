"""Detección de login-walls, checkpoints y rate-limits.

Las funciones de este módulo son puras (url/título/texto -> problema) para poder
testearlas sin navegador; ``read_page_text`` es el único adaptador a Playwright.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from playwright.sync_api import Page

ProblemKind = Literal["login", "checkpoint", "rate_limit"]

_DETAIL_URL_LIMIT = 160

_LOGIN_URL_MARKERS: dict[str, tuple[str, ...]] = {
    "instagram": ("/accounts/login", "/accounts/emailsignup"),
    "facebook": ("/login", "/r.php"),
}
_CHECKPOINT_URL_MARKERS: dict[str, tuple[str, ...]] = {
    "instagram": ("/challenge", "/checkpoint"),
    "facebook": (
        "/checkpoint",
        "/recover",
        "/two_step_verification",
        "/security/checkup",
    ),
}
_RATE_TEXT_MARKERS: tuple[str, ...] = (
    "try again later",
    "temporarily blocked",
    "you're temporarily blocked",
    "rate limit",
    "too many requests",
    "demasiadas solicitudes",
    "inténtalo de nuevo más tarde",
    "intentalo de nuevo mas tarde",
)
_CHECKPOINT_TEXT_MARKERS: tuple[str, ...] = (
    "confirm it's you",
    "help us confirm",
    "unusual activity",
    "we suspended",
    "account has been locked",
    "confirmá que sos vos",
    "confirma que eres tú",
    "actividad inusual",
)

_MAX_BODY_CHARS = 200_000


@dataclass(frozen=True)
class Problem:
    """Problema detectado en una página que impide operar con normalidad."""

    kind: ProblemKind
    detail: str


def _shorten_url(url: str, limit: int = _DETAIL_URL_LIMIT) -> str:
    """Evita arrastrar URLs con tokens gigantes a mensajes y logs."""
    if len(url) <= limit:
        return url
    return url[: limit - 3] + "..."


def detect_problem(platform: str, url: str, title: str, body: str) -> Problem | None:
    """Clasifica una página. Prioridad: checkpoint URL > rate > checkpoint texto > login URL."""
    lower_url = (url or "").lower()
    haystack = f"{(title or '').lower()}\n{(body or '')[:_MAX_BODY_CHARS].lower()}"

    for marker in _CHECKPOINT_URL_MARKERS.get(platform, ()):
        if marker in lower_url:
            return Problem("checkpoint", f"URL de verificación: {_shorten_url(url)}")

    for marker in _RATE_TEXT_MARKERS:
        if marker in haystack:
            return Problem("rate_limit", f"la página avisa un límite temporal ({marker!r})")

    for marker in _CHECKPOINT_TEXT_MARKERS:
        if marker in haystack:
            return Problem("checkpoint", f"la página pide verificación ({marker!r})")

    for marker in _LOGIN_URL_MARKERS.get(platform, ()):
        if marker in lower_url:
            return Problem("login", f"redirige a login ({_shorten_url(url)})")

    return None


def read_page_text(page: Page, limit: int = _MAX_BODY_CHARS) -> str:
    """Texto visible de la página; nunca lanza (página cerrada/crasheada -> "")."""
    from playwright.sync_api import Error as PlaywrightError

    try:
        value = page.evaluate("() => (document.body ? document.body.innerText : '')")
    except PlaywrightError:
        return ""
    if not isinstance(value, str):
        return ""
    return value[:limit]
