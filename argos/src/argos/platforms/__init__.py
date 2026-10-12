"""Registro de plataformas soportadas."""

from __future__ import annotations

from argos.errors import UsageError
from argos.platforms.base import Platform
from argos.platforms.facebook import FacebookPlatform
from argos.platforms.instagram import InstagramPlatform
from argos.platforms.linkedin import LinkedInPlatform
from argos.platforms.x import XPlatform
from argos.platforms.youtube import YouTubePlatform

_PLATFORMS: dict[str, Platform] = {
    InstagramPlatform.name: InstagramPlatform(),
    FacebookPlatform.name: FacebookPlatform(),
    YouTubePlatform.name: YouTubePlatform(),
    LinkedInPlatform.name: LinkedInPlatform(),
    XPlatform.name: XPlatform(),
}


def platform_names() -> tuple[str, ...]:
    return tuple(_PLATFORMS)


def get_platform(name: str) -> Platform:
    key = name.strip().lower()
    try:
        return _PLATFORMS[key]
    except KeyError:
        raise UsageError(
            f"plataforma desconocida: {name!r}",
            hint=f"opciones: {', '.join(_PLATFORMS)}",
        ) from None
