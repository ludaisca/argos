"""Modelos de datos (pydantic v2) — contrato estable para agentes y reportes."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Platform = Literal["instagram", "facebook"]
MediaType = Literal["photo", "video", "carousel", "unknown"]


def _now() -> datetime:
    return datetime.now(UTC)


class Post(BaseModel):
    """Un posteo. En el grid puede venir parcial (sin métricas ni fecha)."""

    model_config = ConfigDict(extra="ignore")

    platform: Platform = "instagram"
    id: str  # shortcode o id de la plataforma
    url: str
    caption: str | None = None
    author: str | None = None
    created_at: datetime | None = None
    likes: int | None = None
    comments: int | None = None
    shares: int | None = None
    views: int | None = None
    media_type: MediaType = "unknown"
    thumbnail_url: str | None = None
    fetched_at: datetime = Field(default_factory=_now)


class Comment(BaseModel):
    model_config = ConfigDict(extra="ignore")

    platform: Platform = "instagram"
    id: str
    url: str  # permalink del comentario
    post_url: str
    author: str | None = None
    text: str = ""
    likes: int | None = None
    age_text: str | None = None  # p. ej. "5d" (relativo, tal como lo muestra IG)
    created_at: datetime | None = None  # aproximada, derivada de age_text
    fetched_at: datetime = Field(default_factory=_now)


class SearchHit(BaseModel):
    model_config = ConfigDict(extra="ignore")

    platform: Platform = "instagram"
    type: Literal["user", "tag", "place", "page", "group", "person"] = "user"
    username: str | None = None
    name: str | None = None
    url: str
    followers: int | None = None
    fetched_at: datetime = Field(default_factory=_now)


class Profile(BaseModel):
    model_config = ConfigDict(extra="ignore")

    platform: Platform = "instagram"
    username: str
    full_name: str | None = None
    bio: str | None = None
    followers: int | None = None
    following: int | None = None
    posts_count: int | None = None
    is_private: bool | None = None
    is_verified: bool | None = None
    profile_pic_url: str | None = None
    external_url: str | None = None
    fetched_at: datetime = Field(default_factory=_now)
