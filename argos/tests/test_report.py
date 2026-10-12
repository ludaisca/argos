"""Reportes: Markdown + CSV + SQLite desde los JSONL."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from argos.errors import UsageError
from argos.models import Comment, Post, Profile, SearchHit
from argos.report import build_report
from argos.store import append_unique_jsonl


def _make_job_dir(tmp_path: Path) -> Path:
    out = tmp_path / "job"
    out.mkdir()
    append_unique_jsonl(
        out / "posts.jsonl",
        [
            Post(
                platform="instagram",
                id="a1",
                url="https://x/p/a1",
                author="nasa",
                caption="hola\nmundo",
                likes=118_000,
                comments=842,
            ),
            Post(platform="facebook", id="b1", url="https://y/", author="NASA", likes=12),
        ],
        ("platform", "id"),
    )
    append_unique_jsonl(
        out / "profiles.jsonl",
        [
            Profile(
                platform="instagram",
                username="nasa",
                full_name="NASA",
                followers=104_000_000,
                is_verified=True,
            )
        ],
        ("platform", "username"),
    )
    append_unique_jsonl(
        out / "comments.jsonl",
        [
            Comment(
                platform="instagram",
                id="c1",
                url="https://x/c1",
                post_url="https://x/p/a1",
                author="alguien",
                text="buen post",
                age_text="5d",
            )
        ],
        ("post_url", "id"),
    )
    append_unique_jsonl(
        out / "search.jsonl",
        [
            SearchHit(
                platform="facebook",
                type="page",
                username="NASA",
                name="NASA",
                url="https://fb/NASA/",
                followers=28_000_000,
            )
        ],
        ("platform", "url"),
    )
    return out


def test_build_report_creates_outputs(tmp_path: Path) -> None:
    out = _make_job_dir(tmp_path)
    result = build_report(out, title="Test")

    markdown = Path(result["markdown"]).read_text(encoding="utf-8")
    assert "# Test" in markdown
    assert "## Resumen" in markdown
    assert "instagram" in markdown and "facebook" in markdown
    assert "118K" in markdown
    assert "buen post" in markdown
    assert "verificada" in markdown

    for name in ("posts", "profiles", "comments", "search"):
        assert (out / f"{name}.csv").exists()

    connection = sqlite3.connect(out / "argos.db")
    try:
        assert connection.execute("SELECT COUNT(*) FROM posts").fetchone()[0] == 2
        assert connection.execute("SELECT likes FROM posts WHERE id='a1'").fetchone()[0] == 118_000
        assert connection.execute("SELECT COUNT(*) FROM profiles").fetchone()[0] == 1
        assert connection.execute("SELECT author FROM comments").fetchone()[0] == "alguien"
    finally:
        connection.close()
    assert result["counts"]["posts"] == 2


def test_report_csv_header(tmp_path: Path) -> None:
    out = _make_job_dir(tmp_path)
    build_report(out)
    header = (out / "posts.csv").read_text(encoding="utf-8").splitlines()[0]
    assert "platform" in header and "likes" in header and "caption" in header


def test_build_report_missing_dir_raises(tmp_path: Path) -> None:
    with pytest.raises(UsageError):
        build_report(tmp_path / "no-existe")


def test_build_report_empty_dir_raises(tmp_path: Path) -> None:
    empty = tmp_path / "vacia"
    empty.mkdir()
    with pytest.raises(UsageError):
        build_report(empty)
