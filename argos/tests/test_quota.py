"""Reporte de cuota (sin navegador)."""

from __future__ import annotations

from pathlib import Path

from argos.quota import quota_report


def test_quota_report_defaults(isolated_home: Path) -> None:
    report = quota_report()
    assert set(report) == {"instagram", "facebook"}
    assert report["instagram"]["used"] == 0
    assert report["instagram"]["daily_limit"] == 400
    assert report["instagram"]["remaining"] == 400
    assert report["instagram"]["per_minute"] == 12
    assert report["facebook"]["per_minute"] == 8


def test_quota_report_reflects_usage(isolated_home: Path) -> None:
    from argos.browser.limiter import RateLimiter
    from argos.config import ArgosConfig

    limiter = RateLimiter(ArgosConfig.load(), "instagram", sleep_fn=lambda _s: None)
    limiter.before_action()
    limiter.before_action()

    report = quota_report()
    assert report["instagram"]["used"] == 2
    assert report["instagram"]["remaining"] == 398
    # facebook no se tocó
    assert report["facebook"]["used"] == 0


def test_quota_report_single_platform(isolated_home: Path) -> None:
    report = quota_report(platform="instagram")
    assert list(report) == ["instagram"]
