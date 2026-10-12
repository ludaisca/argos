"""Instalación del skill (SKILL.md) para agentes."""

from __future__ import annotations

from pathlib import Path

from argos.skill_install import (
    install_skill,
    packaged_skill_path,
    packaged_skill_text,
    uninstall_skill,
)


def test_packaged_skill_has_key_sections() -> None:
    text = packaged_skill_text()
    assert "name: argos" in text
    assert "Solo lectura" in text
    assert "argos quota" in text
    assert "exit" in text


def test_packaged_skill_path_is_a_file() -> None:
    assert packaged_skill_path().name == "SKILL.md"
    assert packaged_skill_path().is_file()


def test_install_and_uninstall(tmp_path: Path) -> None:
    targets = [
        tmp_path / "a" / "skills" / "argos",
        tmp_path / "b" / "skills" / "argos",
    ]
    written = install_skill(targets, "contenido")
    assert len(written) == 2
    assert all(
        path.exists() and path.read_text(encoding="utf-8") == "contenido"
        for path in written
    )

    removed = uninstall_skill(targets)
    assert len(removed) == 2
    assert not any(path.exists() for path in written)


def test_uninstall_is_idempotent(tmp_path: Path) -> None:
    targets = [tmp_path / "skills" / "argos"]
    install_skill(targets, "x")
    assert len(uninstall_skill(targets)) == 1
    assert uninstall_skill(targets) == []  # ya no existe
