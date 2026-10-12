"""Configuración: defaults, parseo, validación y roundtrip."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from argos.config import ArgosConfig, PlatformLimits, resolve_home
from argos.errors import ConfigError
from argos.private_fs import atomic_write_private_text


def test_load_without_file_returns_defaults(isolated_home: Path) -> None:
    config = ArgosConfig.load()
    assert config.home == isolated_home
    assert config.headless is False
    assert config.proxy is None
    assert config.limits_for("instagram") == PlatformLimits(per_minute=12, daily_actions=400)
    assert config.limits_for("facebook") == PlatformLimits(per_minute=8, daily_actions=400)
    assert not (isolated_home / "config.yaml").exists()


def test_load_applies_yaml_overrides(isolated_home: Path) -> None:
    atomic_write_private_text(
        isolated_home / "config.yaml",
        "\n".join(
            [
                "headless: true",
                "locale: es-AR",
                "proxy: http://user:pass@host:8080",
                "limits:",
                "  instagram:",
                "    per_minute: 5",
                "    daily_actions: 10",
            ]
        ),
    )
    config = ArgosConfig.load()
    assert config.headless is True
    assert config.locale == "es-AR"
    assert config.proxy == "http://user:pass@host:8080"
    assert config.limits_for("instagram") == PlatformLimits(per_minute=5, daily_actions=10)
    # Las plataformas no mencionadas conservan los defaults.
    assert config.limits_for("facebook") == PlatformLimits(per_minute=8, daily_actions=400)


@pytest.mark.parametrize(
    "payload, match",
    [
        ("headless: si\n", "headless"),
        ("locale: 42\n", "locale"),
        ("limits: []\n", "limits"),
        ("limits:\n  instagram:\n    per_minute: 0\n", "per_minute"),
        ("limits:\n  instagram:\n    daily_actions: true\n", "daily_actions"),
        ("- una\n- lista\n", "objeto YAML"),
        ("clave: [sin cerrar\n", "inválido"),
    ],
)
def test_invalid_config_raises(isolated_home: Path, payload: str, match: str) -> None:
    atomic_write_private_text(isolated_home / "config.yaml", payload)
    with pytest.raises(ConfigError, match=match):
        ArgosConfig.load()


def test_save_roundtrip(isolated_home: Path) -> None:
    config = ArgosConfig.load()
    config.headless = True
    config.locale = "es-ES"
    config.limits["instagram"] = PlatformLimits(per_minute=3, daily_actions=9)
    config.save()

    reloaded = ArgosConfig.load()
    assert reloaded.headless is True
    assert reloaded.locale == "es-ES"
    assert reloaded.limits_for("instagram") == PlatformLimits(per_minute=3, daily_actions=9)


@pytest.mark.skipif(os.name == "nt", reason="permisos POSIX")
def test_saved_config_is_0600(isolated_home: Path) -> None:
    import stat

    config = ArgosConfig.load()
    config.save()
    mode = stat.S_IMODE((isolated_home / "config.yaml").stat().st_mode)
    assert mode == 0o600


def test_paths_under_home(isolated_home: Path) -> None:
    config = ArgosConfig.load()
    assert config.profile_dir("instagram") == isolated_home / "profiles" / "instagram"
    assert config.state_dir() == isolated_home / "state"
    assert config.debug_dir() == isolated_home / "debug"


def test_resolve_home_prefers_argos_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ARGOS_HOME", str(tmp_path / "custom"))
    monkeypatch.setenv("HOME", str(tmp_path / "otro"))
    assert resolve_home() == (tmp_path / "custom").resolve()


def test_resolve_home_uses_home_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ARGOS_HOME", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    assert resolve_home() == (tmp_path / ".argos").resolve()


def test_resolve_home_falls_back_to_expanduser(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ARGOS_HOME", raising=False)
    monkeypatch.delenv("HOME", raising=False)
    assert resolve_home().name == ".argos"
