"""LinkedIn: perfiles, empresas y búsqueda (requiere sesión del humano)."""

from __future__ import annotations

from argos.platforms.linkedin.extract import (
    is_login_wall,
    me_name,
    parse_posts,
    parse_profile,
    parse_search_results,
)
from argos.platforms.linkedin.flows import (
    ProfileResult,
    SearchResult,
    fetch_profile,
    normalize_target,
    search,
)
from argos.platforms.linkedin.platform import LinkedInPlatform

__all__ = [
    "LinkedInPlatform",
    "ProfileResult",
    "SearchResult",
    "fetch_profile",
    "is_login_wall",
    "me_name",
    "normalize_target",
    "parse_posts",
    "parse_profile",
    "parse_search_results",
    "search",
]
