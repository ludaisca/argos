"""Importación y exportación de cookies de sesión (para usar Argos en un VPS sin navegador).

Estas cookies equivalen a tu contraseña: se guardan en ``~/.argos/config.yaml``
(permisos 0600) y **solo** se inyectan en el navegador cuando el perfil no tiene ya
una sesión válida (así nunca pisamos una sesión fresca con cookies viejas).

Flujo pensado para servers:
  1. En tu máquina con sesión: ``argos cookies instagram --out ig.json``.
  2. Copiá el JSON al VPS.
  3. En el VPS: ``cat ig.json | argos configure ig-cookies --stdin``.
"""

from __future__ import annotations

import json
from typing import Any

COOKIE_DOMAINS = {
    "instagram": ("instagram.com",),
    "facebook": ("facebook.com",),
    "youtube": ("youtube.com", "google.com"),
    "linkedin": ("linkedin.com",),
    "x": ("x.com", "twitter.com"),
}
REQUIRED_COOKIES = {
    "instagram": ("sessionid", "ds_user_id"),
    "facebook": ("c_user", "xs"),
    "linkedin": ("li_at",),
    "x": ("auth_token",),
}
CONFIG_KEYS = {
    "instagram": "ig_cookies",
    "facebook": "fb_cookies",
    "linkedin": "li_cookies",
    "x": "x_cookies",
}
PLATFORM_BY_KEY = {
    "ig-cookies": "instagram",
    "fb-cookies": "facebook",
    "li-cookies": "linkedin",
    "x-cookies": "x",
}
PLATFORM_KEYS = {
    "instagram": "ig-cookies",
    "facebook": "fb-cookies",
    "linkedin": "li-cookies",
    "x": "x-cookies",
}


def _domain_matches(domain: str, platform: str) -> bool:
    host = (domain or "").lower().lstrip(".").rstrip(".")
    if not host:
        return False
    for allowed in COOKIE_DOMAINS.get(platform, ()):
        if host == allowed or host.endswith("." + allowed):
            return True
    return False


def normalize_cookies(cookies: list[dict[str, Any]], platform: str) -> list[dict[str, str]]:
    """Normaliza a ``{name, value, domain, path}``, filtrando otros dominios y duplicados."""
    default_domain = f".{platform}.com"
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in cookies:
        name = str(item.get("name") or "").strip()
        value = str(item.get("value") or "")
        if not name or not value:
            continue
        domain = str(item.get("domain") or default_domain)
        if not _domain_matches(domain, platform):
            continue
        if name in seen:
            continue
        seen.add(name)
        out.append(
            {
                "name": name,
                "value": value,
                "domain": domain if domain.startswith(".") else f".{domain}",
                "path": str(item.get("path") or "/"),
            }
        )
    return out


def parse_cookie_input(value: str, platform: str) -> list[dict[str, str]]:
    """Acepta el JSON de Cookie-Editor (lista) o un header string ``a=b; c=d``."""
    cleaned = value.strip()
    raw: list[dict[str, Any]] = []
    if cleaned.startswith("["):
        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError as exc:
            raise ValueError(f"JSON inválido: {exc}") from exc
        if not isinstance(data, list):
            raise ValueError("el JSON debe ser una lista de cookies")
        for item in data:
            if isinstance(item, dict) and "name" in item and "value" in item:
                raw.append(item)
    else:
        for part in cleaned.split(";"):
            if "=" not in part:
                continue
            name, _, value = part.strip().partition("=")
            name = name.strip()
            value = value.strip()
            if name:
                raw.append({"name": name, "value": value})
    return normalize_cookies(raw, platform)


def export_cookies(context: Any, platform: str) -> list[dict[str, Any]]:
    """Devuelve las cookies del contexto de la plataforma (formato Cookie-Editor)."""
    out: list[dict[str, Any]] = []
    for cookie in context.cookies():
        if not _domain_matches(str(cookie.get("domain") or ""), platform):
            continue
        out.append(
            {
                "name": cookie.get("name"),
                "value": cookie.get("value"),
                "domain": cookie.get("domain"),
                "path": cookie.get("path") or "/",
                "expires": cookie.get("expires"),
            }
        )
    return out


def inject_if_needed(context: Any, platform: str, config: Any) -> bool:
    """Inyecta cookies importadas solo si el perfil no tiene sesión válida."""
    config_key = CONFIG_KEYS.get(platform)
    if config_key is None:
        return False
    imported = config.get(config_key)
    if not isinstance(imported, list) or not imported:
        return False
    required = REQUIRED_COOKIES.get(platform, ())
    existing = {str(cookie.get("name")) for cookie in context.cookies()}
    if any(name in existing for name in required):
        return False
    normalized = normalize_cookies(imported, platform)
    if not normalized:
        return False
    context.add_cookies(
        [
            {
                "name": cookie["name"],
                "value": cookie["value"],
                "domain": cookie["domain"],
                "path": cookie["path"],
            }
            for cookie in normalized
        ]
    )
    return True
