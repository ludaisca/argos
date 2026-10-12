"""Instalación del SKILL.md en los directorios de skills de agentes.

El SKILL.md viaja empaquetado en la rueda (``argos/skill/SKILL.md``); este módulo
permite copiarlo a los directorios que OpenCode, Claude Code y otros agentes
descubren automáticamente.
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from pathlib import Path

_PACKAGED = "skill/SKILL.md"


def packaged_skill_path() -> Path:
    """Ruta al SKILL.md empaquetado (o al del árbol de fuentes en editable)."""
    from importlib.resources import files

    try:
        traversable = files("argos") / "skill" / "SKILL.md"
        if traversable.is_file():
            return Path(str(traversable))
    except (FileNotFoundError, ModuleNotFoundError, AttributeError):
        pass
    return Path(__file__).resolve().parent / "skill" / "SKILL.md"


def packaged_skill_text() -> str:
    return packaged_skill_path().read_text(encoding="utf-8")


def skill_targets() -> list[Path]:
    """Directorios de skills conocidos (respetando HOME para entornos aislados)."""
    home = Path(os.environ.get("HOME") or Path.home())
    return [
        home / ".config" / "opencode" / "skills" / "argos",
        home / ".claude" / "skills" / "argos",
        home / ".agents" / "skills" / "argos",
    ]


def install_skill(targets: Sequence[Path], text: str) -> list[Path]:
    """Escribe SKILL.md en cada destino y devuelve los archivos creados."""
    written: list[Path] = []
    for target in targets:
        target.mkdir(parents=True, exist_ok=True)
        path = target / "SKILL.md"
        path.write_text(text, encoding="utf-8")
        written.append(path)
    return written


def uninstall_skill(targets: Sequence[Path]) -> list[Path]:
    """Borra los SKILL.md instalados y devuelve los que existían."""
    removed: list[Path] = []
    for target in targets:
        path = target / "SKILL.md"
        if path.exists():
            path.unlink()
            removed.append(path)
    return removed
