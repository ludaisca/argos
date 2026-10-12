"""Utilidades de parseo compartidas entre plataformas (fechas y números)."""

from __future__ import annotations

import datetime as dt
import re

_UNITS: dict[str, float] = {
    "segundo": 1 / 86400,
    "second": 1 / 86400,
    "minuto": 1 / 1440,
    "minute": 1 / 1440,
    "hora": 1 / 24,
    "hour": 1 / 24,
    "h": 1 / 24,
    "día": 1,
    "dia": 1,
    "day": 1,
    "d": 1,
    "semana": 7,
    "week": 7,
    "w": 7,
    "mes": 30,
    "month": 30,
    "m": 30,
    "año": 365,
    "ano": 365,
    "year": 365,
}


def parse_relative_date(text: str | None) -> dt.datetime | None:
    """'hace 3 días' / '2 weeks ago' / '2 h' → fecha aproximada (UTC)."""
    if not text:
        return None
    lowered = text.strip().lower().removeprefix("hace ").replace(" ago", "")
    match = re.match(r"(\d+)\s*([a-záéíóúñ]+)", lowered)
    if not match:
        return None
    amount = int(match.group(1))
    unit = match.group(2).rstrip("s")
    days = _UNITS.get(unit)
    if days is None:
        return None
    return dt.datetime.now(dt.UTC) - dt.timedelta(days=amount * days)


def parse_count(text: str | None) -> int | None:
    """'1.234', '1,2 M', '12 mil', '1.2M views', '123,456 vistas' → entero aproximado."""
    if not text:
        return None
    cleaned = text.strip().lower().replace("\xa0", " ")
    match = re.search(r"([\d.,]+)\s*([a-záéíóúñ]*)", cleaned)
    if not match:
        return None
    raw = match.group(1)
    unit = match.group(2).rstrip("s")
    if re.fullmatch(r"\d{1,3}(,\d{3})+", raw):
        raw = raw.replace(",", "")
    elif re.fullmatch(r"\d{1,3}(\.\d{3})+", raw):
        raw = raw.replace(".", "")
    elif "," in raw and "." in raw:
        raw = raw.replace(".", "").replace(",", ".")
    elif "," in raw:
        raw = raw.replace(",", ".")
    try:
        value = float(raw)
    except ValueError:
        return None
    if unit in ("b", "billion"):
        value *= 1_000_000_000
    elif unit in ("m", "millón", "millon", "millone", "million"):
        value *= 1_000_000
    elif unit in ("k", "mil", "thousand"):
        value *= 1_000
    return int(value)
