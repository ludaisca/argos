"""Persistencia JSONL: append, dedupe y claves."""

from __future__ import annotations

from pathlib import Path

from argos.models import Post
from argos.store import append_unique_jsonl


def test_append_unique_jsonl_dedupes(tmp_path: Path) -> None:
    path = tmp_path / "out" / "posts.jsonl"
    batch = [
        Post(id="a", url="https://x/p/a"),
        Post(id="b", url="https://x/p/b"),
    ]

    assert append_unique_jsonl(path, batch, ("platform", "id")) == (2, 0)
    assert append_unique_jsonl(path, batch, ("platform", "id")) == (0, 2)

    more = batch + [Post(id="c", url="https://x/p/c")]
    assert append_unique_jsonl(path, more, ("platform", "id")) == (1, 2)

    lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 3
    assert '"id": "a"' in lines[0]


def test_append_unique_jsonl_ignores_corrupt_lines(tmp_path: Path) -> None:
    path = tmp_path / "posts.jsonl"
    path.write_text("no-json\n", encoding="utf-8")
    written, skipped = append_unique_jsonl(
        path, [Post(id="a", url="u")], ("platform", "id")
    )
    assert (written, skipped) == (1, 0)
