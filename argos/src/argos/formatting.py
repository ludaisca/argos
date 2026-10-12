"""Formateo de números para salidas humanas (CLI y reportes)."""

from __future__ import annotations


def compact_number(value: int | float | None) -> str:
    """118000 -> ``118K``, 1749 -> ``1.7K``, None -> ``—``."""
    if value is None:
        return "—"
    if value >= 1_000_000:
        scaled, suffix = value / 1_000_000, "M"
    elif value >= 1_000:
        scaled, suffix = value / 1_000, "K"
    else:
        return str(int(value))
    text = f"{scaled:.1f}".rstrip("0").rstrip(".")
    return f"{text}{suffix}"
