"""Facebook: probe de sesión, extracción (DOM) y flujos de lectura."""

from argos.platforms.facebook.extract import (
    parse_count_es,
    parse_fb_age,
    parse_posts,
    parse_profile,
    parse_search_results,
)
from argos.platforms.facebook.flows import (
    MAX_POSTS_LIMIT,
    PageResult,
    PostsResult,
    fetch_group_feed,
    fetch_page,
    normalize_page,
    search,
)
from argos.platforms.facebook.platform import FacebookPlatform

__all__ = [
    "MAX_POSTS_LIMIT",
    "FacebookPlatform",
    "PageResult",
    "PostsResult",
    "fetch_group_feed",
    "fetch_page",
    "normalize_page",
    "parse_count_es",
    "parse_fb_age",
    "parse_posts",
    "parse_profile",
    "parse_search_results",
    "search",
]
