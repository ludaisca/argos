"""Plataformas nuevas: YouTube (JSON), LinkedIn y X (DOM con fixtures)."""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable
from typing import Any

import pytest

from argos.platforms.linkedin.extract import (
    parse_posts as li_parse_posts,
)
from argos.platforms.linkedin.extract import (
    parse_search_results as li_parse_search,
)
from argos.platforms.parse_utils import parse_count, parse_relative_date
from argos.platforms.x.extract import (
    parse_profile as x_parse_profile,
)
from argos.platforms.x.extract import (
    parse_tweets as x_parse_tweets,
)
from argos.platforms.youtube.extract import (
    initial_data_from_html,
    parse_channel_meta,
    parse_channel_videos,
    parse_search_channels,
    parse_search_videos,
    parse_video_meta,
    video_id_from,
)

# --------------------------------------------------------------------------- #
# YouTube (JSON de ytInitialData)
# --------------------------------------------------------------------------- #

_LOCKUP: dict[str, Any] = {
    "lockupViewModel": {
        "contentId": "xyz98765432",
        "contentType": "LOCKUP_CONTENT_TYPE_VIDEO",
        "metadata": {
            "lockupMetadataViewModel": {
                "title": {"content": "Short de prueba"},
                "metadata": {
                    "contentMetadataViewModel": {
                        "metadataRows": [
                            {
                                "metadataParts": [
                                    {"text": {"content": "CanalY"}},
                                    {"text": {"content": "12 K vistas"}},
                                ]
                            },
                            {"metadataParts": [{"text": {"content": "hace 2 semanas"}}]},
                        ]
                    }
                },
            }
        },
    }
}

SEARCH_DATA: dict[str, Any] = {
    "contents": {
        "twoColumnSearchResultsRenderer": {
            "primaryContents": {
                "sectionListRenderer": {
                    "contents": [
                        {
                            "itemSectionRenderer": {
                                "contents": [
                                    {
                                        "videoRenderer": {
                                            "videoId": "abc12345678",
                                            "title": {"runs": [{"text": "IA en 2026"}]},
                                            "ownerText": {"runs": [{"text": "CanalX"}]},
                                            "viewCountText": {"simpleText": "1.2M views"},
                                            "publishedTimeText": {"simpleText": "hace 3 días"},
                                            "lengthText": {"simpleText": "10:00"},
                                            "thumbnails": [
                                                {"url": "https://i.ytimg.com/vi/abc12345678/hq.jpg"}
                                            ],
                                        }
                                    },
                                    {
                                        "channelRenderer": {
                                            "channelId": "UC123",
                                            "title": {"simpleText": "CanalX"},
                                            "subscriberCountText": {
                                                "simpleText": "450 mil suscriptores"
                                            },
                                            "navigationEndpoint": {
                                                "browseEndpoint": {"canonicalBaseUrl": "/@canalx"}
                                            },
                                        }
                                    },
                                    _LOCKUP,
                                ]
                            }
                        }
                    ]
                }
            }
        }
    }
}

CHANNEL_DATA: dict[str, Any] = {
    "metadata": {
        "channelMetadataRenderer": {
            "title": "CanalX",
            "description": "Hacemos IA",
        }
    },
    "header": {
        "pageHeaderViewModel": {
            "title": {"dynamicTextViewModel": {"text": {"content": "CanalX Oficial"}}},
            "description": {
                "descriptionPreviewViewModel": {"description": {"content": "Descripción larga"}}
            },
        }
    },
    "subs": {"subscriberCountText": {"content": "1,5 M suscriptores"}},
    "grid": {
        "richGridRenderer": {
            "contents": [
                {
                    "richItemRenderer": {
                        "content": {
                            "videoRenderer": {
                                "videoId": "vid00000001",
                                "title": {"runs": [{"text": "Video del canal"}]},
                                "viewCountText": {"simpleText": "20 mil vistas"},
                            }
                        }
                    }
                }
            ]
        }
    },
}

VIDEO_DATA: dict[str, Any] = {
    "contents": {
        "twoColumnWatchNextResults": {
            "results": {
                "results": {
                    "contents": [
                        {
                            "videoPrimaryInfoRenderer": {
                                "title": {"runs": [{"text": "Cómo funciona Argos"}]},
                                "viewCount": {"runs": [{"text": "123,456 vistas"}]},
                                "dateText": {"simpleText": "Hace 5 días"},
                            }
                        },
                        {
                            "videoSecondaryInfoRenderer": {
                                "owner": {
                                    "videoOwnerRenderer": {
                                        "title": {"runs": [{"text": "ArgosLab"}]}
                                    }
                                }
                            }
                        },
                        {"likeButtonViewModel": {"likeButtonA11y": "1,234 likes"}},
                    ]
                }
            }
        }
    }
}


def test_yt_search_videos_classic_and_lockup() -> None:
    posts = parse_search_videos(SEARCH_DATA, limit=5)
    assert [post.id for post in posts] == ["abc12345678", "xyz98765432"]
    first = posts[0]
    assert first.author == "CanalX"
    assert first.views == 1_200_000
    assert first.created_at is not None
    assert (dt.datetime.now(dt.UTC) - first.created_at).days == 3
    assert first.url == "https://www.youtube.com/watch?v=abc12345678"
    second = posts[1]
    assert second.author == "CanalY"
    assert second.views == 12_000


def test_yt_search_channels() -> None:
    hits = parse_search_channels(SEARCH_DATA, limit=5)
    assert len(hits) == 1
    hit = hits[0]
    assert hit.name == "CanalX"
    assert hit.url == "https://www.youtube.com/@canalx"
    assert hit.followers == 450_000


def test_yt_channel_meta_and_videos() -> None:
    profile = parse_channel_meta(CHANNEL_DATA, "canalx")
    assert profile.full_name == "CanalX"
    assert profile.bio == "Hacemos IA"
    assert profile.followers == 1_500_000
    videos = parse_channel_videos(CHANNEL_DATA, limit=5)
    assert videos and videos[0].id == "vid00000001"
    assert videos[0].views == 20_000


def test_yt_video_meta() -> None:
    post = parse_video_meta(VIDEO_DATA, "abc12345678")
    assert post.caption == "Cómo funciona Argos"
    assert post.author == "ArgosLab"
    assert post.views == 123_456
    assert post.likes == 1_234


def test_yt_helpers() -> None:
    assert video_id_from("https://www.youtube.com/watch?v=dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    assert video_id_from("https://youtu.be/dQw4w9WgXcQ?t=1") == "dQw4w9WgXcQ"
    assert video_id_from("dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    assert video_id_from("no-es-un-video") is None
    assert initial_data_from_html("<script>var ytInitialData = {\"a\": 1};</script>") == {"a": 1}
    assert initial_data_from_html("<html></html>") is None


def test_parse_relative_date_variants() -> None:
    now = dt.datetime.now(dt.UTC)
    two_hours = parse_relative_date("2 hours ago")
    assert two_hours is not None
    assert abs((now - two_hours).total_seconds() - 7200) < 300
    week = parse_relative_date("hace 1 semana")
    assert week is not None and (now - week).days == 7
    weeks = parse_relative_date("3 weeks ago")
    assert weeks is not None and (now - weeks).days == 21
    assert parse_relative_date("siempre") is None
    assert parse_relative_date(None) is None


def test_parse_count_variants() -> None:
    assert parse_count("1.234") == 1234
    assert parse_count("1,2 M seguidores") == 1_200_000
    assert parse_count("12 mil") == 12_000
    assert parse_count("1.2M views") == 1_200_000
    assert parse_count("450 suscriptores") == 450
    assert parse_count("sin números") is None


# --------------------------------------------------------------------------- #
# LinkedIn (DOM)
# --------------------------------------------------------------------------- #


def test_li_search_results(loaded_page: Callable[[str], Any]) -> None:
    page = loaded_page("li_search_people.html")
    people = li_parse_search(page, kind="people", limit=10)
    assert len(people) == 1
    assert people[0].name == "Ana López"
    assert people[0].username == "ana-lopez-123"
    assert people[0].url == "https://www.linkedin.com/in/ana-lopez-123"
    assert people[0].followers is None

    companies = li_parse_search(page, kind="companies", limit=10)
    assert len(companies) == 1
    assert companies[0].name == "Acme Corp"
    assert companies[0].url == "https://www.linkedin.com/company/acme-corp/"
    assert companies[0].followers == 12_000


def test_li_parse_posts(loaded_page: Callable[[str], Any]) -> None:
    page = loaded_page("li_posts.html")
    posts = li_parse_posts(page, limit=10)
    assert len(posts) == 2
    first = posts[0]
    assert first.author == "Ana López"
    assert "contratando" in (first.caption or "")
    assert first.likes == 45
    assert first.comments == 3
    assert first.id == "7300123456789"
    assert first.created_at is not None
    second = posts[1]
    assert second.likes == 1200
    assert second.comments == 28


# --------------------------------------------------------------------------- #
# X (DOM)
# --------------------------------------------------------------------------- #


def test_x_parse_profile(loaded_page: Callable[[str], Any]) -> None:
    page = loaded_page("x_profile.html")
    profile = x_parse_profile(page)
    assert profile.username == "NASA"
    assert profile.full_name == "NASA"
    assert profile.followers == 1_200_000
    assert profile.following == 300
    assert profile.is_verified is True
    assert profile.external_url == "https://nasa.gov"
    assert "universo" in (profile.bio or "")


def test_x_parse_tweets(loaded_page: Callable[[str], Any]) -> None:
    page = loaded_page("x_tweets.html")
    posts = x_parse_tweets(page, limit=10)
    assert len(posts) == 2  # el promocionado se descarta
    first = posts[0]
    assert first.id == "1234567890123456789"
    assert first.author == "NASA"
    assert first.likes == 1234
    assert first.comments == 12
    assert first.shares == 45
    assert first.created_at is not None
    second = posts[1]
    assert second.id == "9876543210987654321"
    assert second.likes == 0  # "Me gusta" sin número → 0


@pytest.mark.parametrize(
    "platform_name,module_attr",
    [
        ("youtube", "argos.platforms.youtube"),
        ("linkedin", "argos.platforms.linkedin"),
        ("x", "argos.platforms.x"),
    ],
)
def test_platforms_registered(platform_name: str, module_attr: str) -> None:
    import importlib

    from argos.platforms import get_platform

    module = importlib.import_module(module_attr)
    platform = get_platform(platform_name)
    assert platform.name == platform_name
    assert module is not None
