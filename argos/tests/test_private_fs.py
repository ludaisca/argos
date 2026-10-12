"""Regresiones de escrituras privadas: 0600/0700, atomicidad y symlinks."""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from argos import private_fs
from argos.private_fs import (
    PrivatePathError,
    atomic_write_private_text,
    read_small_text_no_follow,
)


def test_atomic_write_roundtrip(tmp_path: Path) -> None:
    target = tmp_path / "nested" / "dir" / "config.yaml"
    atomic_write_private_text(target, "hola: mundo\n")
    assert target.read_text(encoding="utf-8") == "hola: mundo\n"
    assert read_small_text_no_follow(target, max_bytes=1024) == "hola: mundo\n"


@pytest.mark.skipif(os.name == "nt", reason="permisos POSIX")
def test_atomic_write_is_0600_and_dir_0700(tmp_path: Path) -> None:
    target = tmp_path / "private" / "secret.txt"
    atomic_write_private_text(target, "secreto")
    assert stat.S_IMODE(target.stat().st_mode) == 0o600
    assert stat.S_IMODE(target.parent.stat().st_mode) == 0o700


def test_atomic_write_keeps_old_file_on_replace_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "private" / "secret.txt"
    target.parent.mkdir()
    target.write_text("viejo", encoding="utf-8")

    def fail_replace(*_args: object, **_kwargs: object) -> None:
        raise OSError("fallo simulado de replace")

    monkeypatch.setattr(private_fs.os, "replace", fail_replace)

    with pytest.raises(OSError, match="fallo simulado"):
        atomic_write_private_text(target, "nuevo")
    assert target.read_text(encoding="utf-8") == "viejo"
    assert list(target.parent.glob(".secret.txt.*.tmp")) == []


def test_read_missing_file_returns_none(tmp_path: Path) -> None:
    assert read_small_text_no_follow(tmp_path / "no-existe.txt", max_bytes=10) is None


def test_read_rejects_oversized_file(tmp_path: Path) -> None:
    target = tmp_path / "grande.txt"
    target.write_text("x" * 100, encoding="utf-8")
    with pytest.raises(PrivatePathError, match="límite de tamaño"):
        read_small_text_no_follow(target, max_bytes=50)


def _symlink_or_skip(link: Path, target: Path, *, directory: bool = False) -> None:
    try:
        link.symlink_to(target, target_is_directory=directory)
    except (OSError, NotImplementedError):
        pytest.skip("este sistema no permite crear symlinks")


def test_write_refuses_symlinked_target(tmp_path: Path) -> None:
    victim = tmp_path / "victim.txt"
    victim.write_text("intacto", encoding="utf-8")
    link = tmp_path / "target.txt"
    _symlink_or_skip(link, victim)

    with pytest.raises(PrivatePathError):
        atomic_write_private_text(link, "malicioso")
    assert victim.read_text(encoding="utf-8") == "intacto"
    assert link.is_symlink()


def test_write_refuses_symlinked_parent(tmp_path: Path) -> None:
    victim_dir = tmp_path / "victim-dir"
    victim_dir.mkdir()
    link = tmp_path / "parent-link"
    _symlink_or_skip(link, victim_dir, directory=True)

    with pytest.raises(PrivatePathError):
        atomic_write_private_text(link / "config.yaml", "malicioso")
    assert list(victim_dir.iterdir()) == []


def test_read_refuses_symlink(tmp_path: Path) -> None:
    victim = tmp_path / "victim.txt"
    victim.write_text("intacto", encoding="utf-8")
    link = tmp_path / "read-link.txt"
    _symlink_or_skip(link, victim)

    with pytest.raises(PrivatePathError):
        read_small_text_no_follow(link, max_bytes=1024)
