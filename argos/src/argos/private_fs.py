"""Escrituras privadas: permisos 0600/0700 y rechazo de symlinks.

Modelo de amenaza: un enlace simbólico en cualquier componente del path no debe
poder redirigir una escritura ni una lectura de configuración, sesión o
evidencia. Los paths se validan antes de abrir y antes de renombrar, y el
reemplazo final es atómico (``os.replace`` sobre el mismo sistema de archivos).
"""

from __future__ import annotations

import contextlib
import os
import stat
import tempfile
from pathlib import Path


class PrivatePathError(RuntimeError):
    """El path atraviesa un symlink o no es un archivo regular."""


def ensure_no_symlink_path(path: str | os.PathLike[str], label: str = "path") -> Path:
    """Rechaza cualquier componente symlink existente, sin resolver el path."""
    target = Path(path)
    absolute = Path(os.path.abspath(os.fspath(target)))
    current = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        current /= part
        try:
            mode = os.lstat(current).st_mode
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(mode):
            raise PrivatePathError(f"{label} no puede atravesar symlinks: {current}")
    return target


def make_private_dir(path: str | os.PathLike[str]) -> Path:
    """Crea (si hace falta) un directorio solo-propietario y verifica el path."""
    target = ensure_no_symlink_path(path, "directorio privado")
    target.mkdir(mode=0o700, parents=True, exist_ok=True)
    ensure_no_symlink_path(target, "directorio privado")
    if os.name != "nt" and hasattr(os, "fchmod"):
        flags = (
            os.O_RDONLY
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_NOFOLLOW", 0)
        )
        dir_fd = os.open(target, flags)
        try:
            os.fchmod(dir_fd, 0o700)
        finally:
            os.close(dir_fd)
    return target


def atomic_write_private_text(
    path: str | os.PathLike[str],
    text: str,
    *,
    encoding: str = "utf-8",
) -> Path:
    """Reemplaza ``path`` de forma atómica con un archivo ``0600``.

    El temporal vive junto al destino para que ``os.replace`` sea atómico en el
    mismo sistema de archivos. Si algo falla, el archivo anterior queda intacto.
    """
    target = Path(path)
    parent = target.parent
    ensure_no_symlink_path(parent, "directorio destino")
    make_private_dir(parent)
    ensure_no_symlink_path(target, "archivo destino")

    fd, tmp_name = tempfile.mkstemp(
        dir=str(parent),
        prefix=f".{target.name}.",
        suffix=".tmp",
    )
    tmp_path = Path(tmp_name)
    try:
        if os.name != "nt" and hasattr(os, "fchmod"):
            os.fchmod(fd, stat.S_IRUSR | stat.S_IWUSR)
        handle = os.fdopen(fd, "w", encoding=encoding)
        fd = -1
        with handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())

        # Un symlink que apareció durante la escritura: fallar cerrado.
        ensure_no_symlink_path(parent, "directorio destino")
        ensure_no_symlink_path(target, "archivo destino")
        os.replace(tmp_path, target)

        if os.name != "nt" and hasattr(os, "O_DIRECTORY"):
            try:
                dir_fd = os.open(
                    parent,
                    os.O_RDONLY
                    | os.O_DIRECTORY
                    | getattr(os, "O_NOFOLLOW", 0),
                )
                try:
                    os.fsync(dir_fd)
                finally:
                    os.close(dir_fd)
            except OSError:
                pass
    except BaseException:
        if fd >= 0:
            with contextlib.suppress(OSError):
                os.close(fd)
        with contextlib.suppress(OSError):
            tmp_path.unlink(missing_ok=True)
        raise
    return target


def read_small_text_no_follow(
    path: str | os.PathLike[str],
    *,
    max_bytes: int,
    encoding: str = "utf-8",
) -> str | None:
    """Lee un archivo regular acotado, rechazando symlinks en todo el path.

    Devuelve ``None`` si el archivo no existe. Lanza ``PrivatePathError`` si el
    path atraviesa un symlink, no es un archivo regular, o excede ``max_bytes``.
    """
    if max_bytes < 0:
        raise ValueError("max_bytes debe ser >= 0")

    target = ensure_no_symlink_path(path, "lectura")
    flags = (
        os.O_RDONLY
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_NONBLOCK", 0)
        | getattr(os, "O_CLOEXEC", 0)
    )
    try:
        fd = os.open(target, flags)
    except FileNotFoundError:
        return None

    try:
        file_stat = os.fstat(fd)
        if not stat.S_ISREG(file_stat.st_mode):
            raise PrivatePathError(f"el destino no es un archivo regular: {target}")
        if file_stat.st_size > max_bytes:
            raise PrivatePathError(f"el destino supera el límite de tamaño: {target}")

        chunks: list[bytes] = []
        remaining = max_bytes + 1
        while remaining > 0:
            chunk = os.read(fd, remaining)
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        payload = b"".join(chunks)
        if len(payload) > max_bytes:
            raise PrivatePathError(f"el destino supera el límite de tamaño: {target}")
        ensure_no_symlink_path(target, "lectura")
    finally:
        os.close(fd)
    return payload.decode(encoding)
