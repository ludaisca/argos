"""Informes: convierte los JSONL de una carpeta de salida en Markdown + CSV + SQLite.

Es la pieza que transforma datos crudos en algo legible/consultable. No usa
navegador ni red: solo lee ``posts.jsonl`` / ``profiles.jsonl`` /
``comments.jsonl`` / ``search.jsonl`` y escribe ``report.md``, los CSV y
``argos.db``.
"""

from __future__ import annotations

import csv
import datetime as dt
from pathlib import Path
from typing import Any

from argos.errors import UsageError
from argos.formatting import compact_number
from argos.store import load_jsonl, write_sqlite

#: tabla → (archivo JSONL, campos clave)
DATASETS: dict[str, tuple[str, tuple[str, ...]]] = {
    "posts": ("posts.jsonl", ("platform", "id")),
    "profiles": ("profiles.jsonl", ("platform", "username")),
    "comments": ("comments.jsonl", ("post_url", "id")),
    "search": ("search.jsonl", ("platform", "url")),
}

CSV_COLUMNS: dict[str, list[str]] = {
    "posts": [
        "platform", "id", "author", "created_at", "likes", "comments", "shares",
        "views", "media_type", "caption", "url", "thumbnail_url",
    ],
    "profiles": [
        "platform", "username", "full_name", "followers", "following", "posts_count",
        "is_private", "is_verified", "bio", "external_url", "profile_pic_url",
    ],
    "comments": ["platform", "post_url", "id", "author", "text", "age_text", "created_at", "url"],
    "search": ["platform", "type", "username", "name", "followers", "url"],
}


def load_datasets(out_dir: Path) -> dict[str, list[dict[str, Any]]]:
    return {
        name: load_jsonl(out_dir / filename) for name, (filename, _keys) in DATASETS.items()
    }


def _truncate(value: Any, limit: int) -> str:
    text = ("" if value is None else str(value)).replace("\n", " ").strip()
    return text[:limit] + ("…" if len(text) > limit else "")


def _table(rows: list[list[str]], headers: list[str]) -> list[str]:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        cells = [cell.replace("|", "\\|") for cell in row]
        lines.append("| " + " | ".join(cells) + " |")
    return lines


def _by_platform(records: list[dict[str, Any]], platform: str) -> list[dict[str, Any]]:
    return [record for record in records if record.get("platform") == platform]


def render_markdown(datasets: dict[str, list[dict[str, Any]]], *, title: str) -> str:
    now = dt.datetime.now(dt.UTC).isoformat(timespec="seconds")
    lines = [f"# {title}", "", f"Generado: {now}", ""]

    lines.append("## Resumen")
    lines.append("")
    for name in ("posts", "profiles", "comments", "search"):
        records = datasets.get(name, [])
        counts: dict[str, int] = {}
        for record in records:
            key = str(record.get("platform") or "?")
            counts[key] = counts.get(key, 0) + 1
        detail = ", ".join(f"{key} {value}" for key, value in sorted(counts.items()))
        lines.append(f"- **{name}**: {len(records)}" + (f" ({detail})" if detail else ""))
    lines.append("")

    platforms = sorted(
        {
            str(record.get("platform"))
            for records in datasets.values()
            for record in records
            if record.get("platform")
        }
    )

    for platform in platforms:
        lines.append(f"## {platform.capitalize()}")
        lines.append("")

        profiles = _by_platform(datasets.get("profiles", []), platform)
        if profiles:
            lines.append("### Perfiles")
            lines.append("")
            rows = [
                [
                    f"@{record.get('username') or ''}",
                    _truncate(record.get("full_name"), 40) or "—",
                    compact_number(record.get("followers")),
                    compact_number(record.get("following")),
                    compact_number(record.get("posts_count")),
                    "sí" if record.get("is_verified") else "",
                ]
                for record in profiles
            ]
            lines += _table(
                rows,
                ["usuario", "nombre", "seguidores", "siguiendo", "posts", "verificada"],
            )
            lines.append("")

        posts = _by_platform(datasets.get("posts", []), platform)
        if posts:
            lines.append(f"### Posts ({len(posts)})")
            lines.append("")
            rows = [
                [
                    str(record.get("created_at") or "")[:10] or "—",
                    _truncate(record.get("author"), 24) or "—",
                    compact_number(record.get("likes")),
                    compact_number(record.get("comments")),
                    compact_number(record.get("shares")),
                    compact_number(record.get("views")),
                    _truncate(record.get("caption"), 70),
                    str(record.get("url") or ""),
                ]
                for record in posts
            ]
            lines += _table(
                rows,
                ["fecha", "autor", "likes", "coment.", "shares", "views", "caption", "url"],
            )
            lines.append("")

        comments = _by_platform(datasets.get("comments", []), platform)
        if comments:
            lines.append(f"### Comentarios ({len(comments)})")
            lines.append("")
            rows = [
                [
                    f"@{record.get('author') or ''}",
                    _truncate(record.get("text"), 90),
                    str(record.get("age_text") or ""),
                ]
                for record in comments
            ]
            lines += _table(rows, ["autor", "texto", "antigüedad"])
            lines.append("")

        hits = _by_platform(datasets.get("search", []), platform)
        if hits:
            lines.append(f"### Resultados de búsqueda ({len(hits)})")
            lines.append("")
            rows = [
                [
                    _truncate(record.get("name"), 40) or "—",
                    str(record.get("type") or ""),
                    compact_number(record.get("followers")),
                    str(record.get("url") or ""),
                ]
                for record in hits
            ]
            lines += _table(rows, ["nombre", "tipo", "seguidores", "url"])
            lines.append("")

    if not platforms:
        lines.append("_No hay datos en esta carpeta (¿corriste algún comando con `--out`?)._")
    return "\n".join(lines).rstrip() + "\n"


def _write_csv(path: Path, records: list[dict[str, Any]], columns: list[str]) -> int:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for record in records:
            writer.writerow(
                {
                    column: ("" if record.get(column) is None else record.get(column))
                    for column in columns
                }
            )
    return len(records)


def build_report(out_dir: Path, *, title: str | None = None) -> dict[str, Any]:
    """Genera ``report.md``, CSVs y ``argos.db`` desde los JSONL de ``out_dir``."""
    out_dir = Path(out_dir)
    if not out_dir.is_dir():
        raise UsageError(
            f"la carpeta no existe: {out_dir}",
            hint="pasá una carpeta con posts.jsonl / profiles.jsonl / …",
        )
    datasets = load_datasets(out_dir)
    total = sum(len(records) for records in datasets.values())
    if total == 0:
        raise UsageError(
            f"no hay datos en {out_dir}",
            hint="corré algún comando con `--out DIR` y volvé a intentar",
        )

    job_title = title or f"Informe Argos — {out_dir.name}"
    report_path = out_dir / "report.md"
    report_path.write_text(render_markdown(datasets, title=job_title), encoding="utf-8")

    csv_paths: list[str] = []
    for name, columns in CSV_COLUMNS.items():
        records = datasets.get(name, [])
        if not records:
            continue
        csv_path = out_dir / f"{name}.csv"
        _write_csv(csv_path, records, columns)
        csv_paths.append(str(csv_path))

    db_path = out_dir / "argos.db"
    counts = write_sqlite(
        db_path,
        {name: (records, DATASETS[name][1]) for name, records in datasets.items()},
    )
    return {
        "directory": str(out_dir),
        "markdown": str(report_path),
        "csv": csv_paths,
        "db": str(db_path),
        "counts": counts,
    }
