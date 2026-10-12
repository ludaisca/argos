"""Importación/exportación/inyección de cookies de sesión."""

from __future__ import annotations

import json

import pytest

from argos.cookies import (
    CONFIG_KEYS,
    export_cookies,
    inject_if_needed,
    normalize_cookies,
    parse_cookie_input,
)


def test_parse_json_cookie_editor() -> None:
    payload = json.dumps(
        [
            {"name": "sessionid", "value": "abc", "domain": ".instagram.com", "path": "/"},
            {"name": "ds_user_id", "value": "123", "domain": ".instagram.com", "path": "/"},
            {"name": "evil", "value": "x", "domain": ".evil.com", "path": "/"},
            {"name": "no_value", "domain": ".instagram.com"},
        ]
    )
    cookies = parse_cookie_input(payload, "instagram")
    names = [cookie["name"] for cookie in cookies]
    assert names == ["sessionid", "ds_user_id"]
    assert cookies[0]["domain"] == ".instagram.com"


def test_parse_header_string() -> None:
    cookies = parse_cookie_input("c_user=100; xs=xyz; fr=abc", "facebook")
    assert [cookie["name"] for cookie in cookies] == ["c_user", "xs", "fr"]
    assert all(cookie["domain"] == ".facebook.com" for cookie in cookies)


def test_parse_invalid_json_raises() -> None:
    with pytest.raises(ValueError):
        parse_cookie_input("[not json", "instagram")


def test_normalize_dedupes_by_name() -> None:
    out = normalize_cookies(
        [
            {"name": "a", "value": "1"},
            {"name": "a", "value": "2"},
            {"name": "b", "value": "3"},
        ],
        "instagram",
    )
    assert [cookie["name"] for cookie in out] == ["a", "b"]
    assert out[0]["value"] == "1"


class FakeContext:
    def __init__(self, names: list[str]) -> None:
        self._names = set(names)
        self.added = None

    def cookies(self) -> list[dict[str, object]]:
        return [
            {"name": name, "value": "v", "domain": ".instagram.com", "path": "/"}
            for name in self._names
        ]

    def add_cookies(self, cookies: list[dict[str, str]]) -> None:
        self.added = cookies


class FakeConfig:
    def __init__(self, values: dict[str, object] | None = None) -> None:
        self._values = values or {}

    def get(self, key: str) -> object:
        return self._values.get(key)


def test_inject_when_profile_has_no_session() -> None:
    context = FakeContext(["csrftoken"])  # sin sessionid/ds_user_id
    config = FakeConfig(
        {
            CONFIG_KEYS["instagram"]: [
                {"name": "sessionid", "value": "abc", "domain": ".instagram.com", "path": "/"},
                {"name": "ds_user_id", "value": "123", "domain": ".instagram.com", "path": "/"},
            ]
        }
    )
    assert inject_if_needed(context, "instagram", config) is True
    assert context.added is not None
    assert {cookie["name"] for cookie in context.added} == {"sessionid", "ds_user_id"}


def test_no_inject_when_session_present() -> None:
    context = FakeContext(["sessionid", "ds_user_id"])
    config = FakeConfig(
        {
            CONFIG_KEYS["instagram"]: [
                {"name": "sessionid", "value": "old", "domain": ".instagram.com", "path": "/"}
            ]
        }
    )
    assert inject_if_needed(context, "instagram", config) is False
    assert context.added is None


def test_no_inject_without_imported_cookies() -> None:
    assert inject_if_needed(FakeContext([]), "instagram", FakeConfig()) is False


def test_export_filters_domains() -> None:
    class Ctx:
        def cookies(self) -> list[dict[str, object]]:
            return [
                {
                    "name": "sessionid",
                    "value": "abc",
                    "domain": ".instagram.com",
                    "path": "/",
                    "expires": -1,
                },
                {
                    "name": "other",
                    "value": "x",
                    "domain": ".other.com",
                    "path": "/",
                    "expires": -1,
                },
            ]

    out = export_cookies(Ctx(), "instagram")
    assert [cookie["name"] for cookie in out] == ["sessionid"]
