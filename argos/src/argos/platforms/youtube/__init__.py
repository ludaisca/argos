"""YouTube: búsqueda, canales y videos (público, sin login)."""

from __future__ import annotations

from argos.platforms.parse_utils import parse_relative_date
from argos.platforms.youtube.extract import (
    initial_data,
    parse_channel_meta,
    parse_channel_videos,
    parse_comments,
    parse_search_channels,
    parse_search_videos,
    parse_video_meta,
    video_id_from,
)
from argos.platforms.youtube.flows import (
    ChannelResult,
    SearchResult,
    VideoResult,
    fetch_channel,
    fetch_video,
    search,
)
from argos.platforms.youtube.platform import YouTubePlatform

__all__ = [
    "ChannelResult",
    "SearchResult",
    "VideoResult",
    "YouTubePlatform",
    "fetch_channel",
    "fetch_video",
    "initial_data",
    "parse_channel_meta",
    "parse_channel_videos",
    "parse_comments",
    "parse_relative_date",
    "parse_search_channels",
    "parse_search_videos",
    "parse_video_meta",
    "search",
    "video_id_from",
]
