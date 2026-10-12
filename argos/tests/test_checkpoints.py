"""Detección de login-walls, checkpoints y rate-limits (funciones puras)."""

from __future__ import annotations

import dataclasses

import pytest

from argos.browser.checkpoints import Problem, detect_problem


@pytest.mark.parametrize(
    "platform, url, title, body, kind",
    [
        (
            "instagram",
            "https://www.instagram.com/challenge/",
            "",
            "",
            "checkpoint",
        ),
        (
            "facebook",
            "https://www.facebook.com/checkpoint/1501092823525282/",
            "",
            "",
            "checkpoint",
        ),
        (
            "facebook",
            "https://www.facebook.com/login/?next=%2Fme",
            "",
            "",
            "login",
        ),
        (
            "instagram",
            "https://www.instagram.com/accounts/login/?next=/",
            "",
            "",
            "login",
        ),
        (
            "instagram",
            "https://www.instagram.com/",
            "Instagram",
            "Try again later\nno pudimos cargar",
            "rate_limit",
        ),
        (
            "facebook",
            "https://www.facebook.com/me",
            "",
            "We suspended your account",
            "checkpoint",
        ),
        (
            "facebook",
            "https://www.facebook.com/me",
            "",
            "Actividad inusual detectada",
            "checkpoint",
        ),
        (
            "instagram",
            "https://www.instagram.com/",
            "Instagram",
            "bienvenido a tu feed",
            None,
        ),
    ],
)
def test_detect_problem(
    platform: str, url: str, title: str, body: str, kind: str | None
) -> None:
    problem = detect_problem(platform, url, title, body)
    if kind is None:
        assert problem is None
    else:
        assert problem is not None
        assert problem.kind == kind


def test_checkpoint_url_wins_over_rate_text() -> None:
    problem = detect_problem(
        "instagram",
        "https://www.instagram.com/checkpoint/",
        "",
        "try again later",
    )
    assert problem is not None
    assert problem.kind == "checkpoint"


def test_problem_is_frozen_dataclass() -> None:
    problem = Problem("login", "detalle")
    with pytest.raises(dataclasses.FrozenInstanceError):
        problem.kind = "checkpoint"  # type: ignore[misc]


def test_unknown_platform_has_no_url_markers() -> None:
    assert detect_problem("tiktok", "https://example.com/login", "", "") is None


def test_long_challenge_url_is_truncated() -> None:
    url = "https://www.instagram.com/auth_platform/challengepicker/?apc=" + ("A" * 500)
    problem = detect_problem("instagram", url, "", "")
    assert problem is not None
    assert problem.kind == "checkpoint"
    assert len(problem.detail) < 200
    assert problem.detail.endswith("...")
