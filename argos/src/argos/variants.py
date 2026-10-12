"""Generación de variantes de nombre para búsquedas de personas.

Separado en dos familias porque cada red matchea distinto:
  - Facebook (búsqueda de personas) matchea por nombre mostrado → variantes con
    espacios (quitar apellido, invertir apellidos, etc.).
  - Instagram (búsqueda de usuarios) matchea por *username* → variantes estilo
    handle (junto, con punto, con guion bajo).
"""

from __future__ import annotations

import re

_SPLIT_RE = re.compile(r"[\s_.+/-]+")

MAX_VARIANTS = 6


def split_name(value: str) -> list[str]:
    """Divide un nombre en sus palabras, sin importar el separador."""
    return [part for part in _SPLIT_RE.split(value.strip()) if part]


def name_variants(value: str) -> list[str]:
    """Variantes con espacios, pensadas para búsqueda de personas (Facebook).

    ``"Uriel Arriaga Garcia"`` →
    ``["Uriel Arriaga Garcia", "Uriel Arriaga", "Uriel Garcia", "Uriel Garcia Arriaga"]``
    """
    parts = split_name(value)
    if not parts:
        return []
    first = parts[0]
    rest = parts[1:]

    variants: list[str] = [" ".join(parts)]
    if rest:
        variants.append(" ".join([first] + rest[:-1]))
    if len(rest) >= 2:
        variants.append(" ".join([first, rest[-1]]))
        variants.append(" ".join([first, rest[-1], rest[0]]))

    return _dedupe(variants)[:MAX_VARIANTS]


def username_variants(value: str) -> list[str]:
    """Variantes estilo username, pensadas para búsqueda de usuarios (Instagram).

    ``"Uriel Arriaga Garcia"`` →
    ``["urielarriagagarcia", "uriel.arriaga.garcia", "uriel_arriaga_garcia",
      "urielgarcia", "uriel.garcia"]``
    """
    parts = split_name(value)
    if not parts:
        return []

    joined = "".join(parts).lower()
    dotted = ".".join(parts).lower()
    underscored = "_".join(parts).lower()
    variants: list[str] = [joined, dotted, underscored]
    if len(parts) >= 2:
        variants.append((parts[0] + parts[-1]).lower())
        variants.append((parts[0] + "." + parts[-1]).lower())
        variants.append((parts[0] + "_" + parts[-1]).lower())

    return _dedupe(variants)[:MAX_VARIANTS]


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            out.append(value)
    return out
