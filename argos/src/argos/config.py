"""Configuración de Argos.

El home por defecto es ``~/.argos`` y se puede mover con ``ARGOS_HOME``. En
plataformas donde ``HOME`` esté definido se respeta (tests, contenedores,
entornos de agentes); el resto de las veces se usa ``expanduser``.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from argos.errors import ConfigError
from argos.private_fs import atomic_write_private_text, read_small_text_no_follow

APP_DIRNAME = ".argos"
_MAX_CONFIG_BYTES = 1024 * 1024


def resolve_home() -> Path:
    """Ruta base de todo el estado de Argos."""
    override = os.environ.get("ARGOS_HOME")
    if override:
        return Path(os.path.abspath(os.path.expanduser(override)))
    env_home = os.environ.get("HOME")
    if env_home:
        return Path(os.path.abspath(env_home)) / APP_DIRNAME
    return Path(os.path.expanduser("~")) / APP_DIRNAME


@dataclass(frozen=True)
class PlatformLimits:
    """Límites por plataforma: ritmo (token bucket) y techo diario."""

    per_minute: int = 12
    daily_actions: int = 400


DEFAULT_LIMITS: Mapping[str, PlatformLimits] = {
    "instagram": PlatformLimits(per_minute=12, daily_actions=400),
    "facebook": PlatformLimits(per_minute=8, daily_actions=400),
}


@dataclass
class ArgosConfig:
    home: Path
    headless: bool = False
    locale: str | None = None
    timezone_id: str | None = None
    proxy: str | None = None
    limits: dict[str, PlatformLimits] = field(
        default_factory=lambda: dict(DEFAULT_LIMITS)
    )
    extra: dict[str, Any] = field(default_factory=dict)
    source_path: Path | None = None

    @classmethod
    def load(cls, home: Path | None = None) -> ArgosConfig:
        """Carga la config; si no existe, devuelve defaults sin crear archivos."""
        base = home if home is not None else resolve_home()
        path = base / "config.yaml"
        config = cls(home=base, source_path=path)

        raw = read_small_text_no_follow(path, max_bytes=_MAX_CONFIG_BYTES)
        if raw is None:
            return config
        try:
            data = yaml.safe_load(raw)
        except yaml.YAMLError as exc:
            raise ConfigError(f"config.yaml inválido: {exc}") from exc
        if data is None:
            return config
        if not isinstance(data, dict):
            raise ConfigError("config.yaml debe ser un objeto YAML")
        config._apply(data)
        return config

    def _apply(self, data: Mapping[str, Any]) -> None:
        known = {"headless", "locale", "timezone_id", "proxy", "limits"}
        for key, value in data.items():
            if key not in known:
                self.extra[key] = value
        if "headless" in data:
            value = data["headless"]
            if not isinstance(value, bool):
                raise ConfigError("`headless` debe ser true/false")
            self.headless = value
        for key in ("locale", "timezone_id", "proxy"):
            if key in data:
                value = data[key]
                if value is not None and not isinstance(value, str):
                    raise ConfigError(f"`{key}` debe ser texto o null")
                setattr(self, key, value)
        if "limits" in data:
            self.limits = _parse_limits(data["limits"])

    def save(self) -> None:
        """Escribe la config efectiva en ``~/.argos/config.yaml`` (0600)."""
        payload: dict[str, Any] = {
            "headless": self.headless,
            "locale": self.locale,
            "timezone_id": self.timezone_id,
            "proxy": self.proxy,
            "limits": {
                name: {
                    "per_minute": limits.per_minute,
                    "daily_actions": limits.daily_actions,
                }
                for name, limits in self.limits.items()
            },
        }
        payload.update(self.extra)
        atomic_write_private_text(
            self.home / "config.yaml",
            yaml.safe_dump(payload, allow_unicode=True, sort_keys=True),
        )

    def get(self, key: str, default: Any = None) -> Any:
        """Lee una clave extra (p. ej. ``ig_cookies``); sin fallar si falta."""
        return self.extra.get(key, default)

    def set(self, key: str, value: Any) -> None:
        """Guarda una clave extra y persiste la config."""
        self.extra[key] = value
        self.save()

    def limits_for(self, platform: str) -> PlatformLimits:
        return self.limits.get(platform, PlatformLimits())

    def profile_dir(self, platform: str) -> Path:
        return self.home / "profiles" / platform

    def state_dir(self) -> Path:
        return self.home / "state"

    def debug_dir(self) -> Path:
        return self.home / "debug"


def _parse_limits(raw: object) -> dict[str, PlatformLimits]:
    if not isinstance(raw, dict):
        raise ConfigError("`limits` debe ser un objeto por plataforma")
    merged: dict[str, PlatformLimits] = dict(DEFAULT_LIMITS)
    for name, value in raw.items():
        if not isinstance(name, str):
            raise ConfigError("`limits` contiene un nombre de plataforma inválido")
        if not isinstance(value, dict):
            raise ConfigError(f"limits.{name} debe ser un objeto")
        base = DEFAULT_LIMITS.get(name, PlatformLimits())
        merged[name] = PlatformLimits(
            per_minute=_positive_int(
                value.get("per_minute", base.per_minute),
                f"limits.{name}.per_minute",
            ),
            daily_actions=_positive_int(
                value.get("daily_actions", base.daily_actions),
                f"limits.{name}.daily_actions",
            ),
        )
    return merged


def _positive_int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ConfigError(f"`{label}` debe ser un entero >= 1")
    return value
