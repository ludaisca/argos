"""X (Twitter): perfiles y búsqueda (requiere sesión del humano)."""

from __future__ import annotations

from argos.platforms.x.extract import (
    is_login_wall,
    me_handle,
    parse_profile,
    parse_tweets,
)
from argos.platforms.x.flows import (
    ProfileResult,
    SearchResult,
    fetch_profile,
    normalize_handle,
    search,
)
from argos.platforms.x.platform import XPlatform

__all__ = [
    "ProfileResult",
    "SearchResult",
    "XPlatform",
    "fetch_profile",
    "is_login_wall",
    "me_handle",
    "normalize_handle",
    "parse_profile",
    "parse_tweets",
    "search",
]
