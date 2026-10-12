"""Persistencia: JSONL append-only con dedupe por clave + export a SQLite.

Los JSONL son la fuente de verdad (append-only, sin pérdidas); el SQLite que
genera ``argos report`` es una vista consultable construida desde ellos.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from pydantic import BaseModel


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    """Lee un JSONL completo; ignora líneas vacías o corruptas."""
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(record, dict):
            out.append(record)
    return out


def _column_type(values: list[Any]) -> str:
    non_null = [value for value in values if value is not None]
    if non_null and all(isinstance(v, int) and not isinstance(v, bool) for v in non_null):
        return "INTEGER"
    if non_null and all(
        isinstance(v, (int, float)) and not isinstance(v, bool) for v in non_null
    ):
        return "REAL"
    return "TEXT"


def write_sqlite(
    db_path: Path,
    datasets: dict[str, tuple[list[dict[str, Any]], tuple[str, ...]]],
) -> dict[str, int]:
    """Escribe datasets en SQLite (INSERT OR REPLACE por clave) y devuelve filas por tabla.

    El esquema se infiere de los datos: columnas = unión de claves, tipos por
    contenido, PRIMARY KEY = campos clave del dataset.
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    counts: dict[str, int] = {}
    connection = sqlite3.connect(db_path)
    try:
        for name, (records, key_fields) in datasets.items():
            if not records:
                counts[name] = 0
                continue
            columns = sorted({key for record in records for key in record})
            definitions = ", ".join(
                f'"{column}" {_column_type([record.get(column) for record in records])}'
                for column in columns
            )
            primary_key = ", ".join(f'"{field}"' for field in key_fields)
            connection.execute(
                f'CREATE TABLE IF NOT EXISTS "{name}" ({definitions}, '
                f"PRIMARY KEY ({primary_key}))"
            )
            connection.execute(f'DELETE FROM "{name}"')  # vista reconstruida
            column_list = ", ".join(f'"{column}"' for column in columns)
            placeholders = ", ".join("?" for _ in columns)
            rows = [
                tuple(
                    json.dumps(record.get(column), ensure_ascii=False)
                    if isinstance(record.get(column), (dict, list))
                    else record.get(column)
                    for column in columns
                )
                for record in records
            ]
            connection.executemany(
                f'INSERT OR REPLACE INTO "{name}" ({column_list}) VALUES ({placeholders})',
                rows,
            )
            counts[name] = len(rows)
        connection.commit()
    finally:
        connection.close()
    return counts


def _load_keys(path: Path, key_fields: tuple[str, ...]) -> set[tuple[Any, ...]]:
    keys: set[tuple[Any, ...]] = set()
    for record in load_jsonl(path):
        keys.add(tuple(record.get(field) for field in key_fields))
    return keys


def append_unique_jsonl(
    path: Path,
    records: Iterable[BaseModel],
    key_fields: tuple[str, ...],
) -> tuple[int, int]:
    """Agrega registros sin duplicar claves existentes.

    Devuelve ``(escritos, omitidos)``.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = _load_keys(path, key_fields)
    written = 0
    skipped = 0
    with path.open("a", encoding="utf-8") as handle:
        for record in records:
            payload = record.model_dump(mode="json")
            key = tuple(payload.get(field) for field in key_fields)
            if key in existing:
                skipped += 1
                continue
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
            existing.add(key)
            written += 1
    return written, skipped
