"""Límites: token bucket, cuota diaria persistida y fachada."""

from __future__ import annotations

from pathlib import Path

import pytest

from argos.browser.limiter import DailyQuota, RateLimiter, TokenBucket
from argos.config import ArgosConfig, PlatformLimits
from argos.errors import RateLimitedError


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def time(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


def test_bucket_allows_burst_then_waits() -> None:
    clock = FakeClock()
    bucket = TokenBucket(
        rate_per_minute=60,
        capacity=1,
        time_fn=clock.time,
        sleep_fn=clock.sleep,
    )
    assert bucket.try_acquire() is True
    assert bucket.try_acquire() is False
    bucket.acquire()  # debe esperar exactamente 1 segundo (60/min)
    assert clock.now == pytest.approx(1.0)


def test_bucket_refills_proportionally() -> None:
    clock = FakeClock()
    bucket = TokenBucket(
        rate_per_minute=120,
        capacity=2,
        time_fn=clock.time,
        sleep_fn=clock.sleep,
    )
    assert bucket.try_acquire(2.0) is True
    clock.sleep(0.5)  # 120/min => 1 token por 0.5 s
    assert bucket.try_acquire() is True
    assert bucket.try_acquire() is False


def test_bucket_rejects_invalid_params() -> None:
    with pytest.raises(ValueError):
        TokenBucket(rate_per_minute=0)
    bucket = TokenBucket(rate_per_minute=1, capacity=1, sleep_fn=lambda _s: None)
    with pytest.raises(ValueError):
        bucket.try_acquire(2.0)


def test_quota_blocks_and_persists(tmp_path: Path) -> None:
    state = tmp_path / "state" / "limits.json"
    quota = DailyQuota(state, "instagram", 3, day_fn=lambda: "2026-09-30")

    assert quota.remaining() == 3
    quota.consume()
    quota.consume()
    assert quota.remaining() == 1

    with pytest.raises(RateLimitedError, match="cuota diaria"):
        quota.consume(2)

    # Persistencia: una instancia nueva ve el conteo.
    reloaded = DailyQuota(state, "instagram", 3, day_fn=lambda: "2026-09-30")
    assert reloaded.used() == 2


def test_quota_resets_on_new_day(tmp_path: Path) -> None:
    state = tmp_path / "state" / "limits.json"
    day = {"value": "2026-09-30"}
    quota = DailyQuota(state, "instagram", 1, day_fn=lambda: day["value"])

    quota.consume()
    with pytest.raises(RateLimitedError):
        quota.consume()

    day["value"] = "2026-10-01"
    assert quota.remaining() == 1


def test_quota_prunes_old_days(tmp_path: Path) -> None:
    state = tmp_path / "state" / "limits.json"
    quota = DailyQuota(state, "instagram", 5, day_fn=lambda: "2026-09-30")
    quota.consume()
    text = state.read_text(encoding="utf-8")
    assert "2026-09-30" in text

    later = DailyQuota(state, "instagram", 5, day_fn=lambda: "2026-10-20")
    later.consume()
    text = later._load()  # noqa: SLF001 - verificamos el archivo resultante
    assert list(text["days"]) == ["2026-10-20"]


def test_rate_limiter_facade_enforces_daily_limit(isolated_home: Path) -> None:
    config = ArgosConfig.load()
    config.limits["instagram"] = PlatformLimits(per_minute=600, daily_actions=1)
    clock = FakeClock()
    limiter = RateLimiter(config, "instagram", sleep_fn=clock.sleep)

    assert limiter.before_action() == 0
    with pytest.raises(RateLimitedError):
        limiter.before_action()


def test_rate_limiter_facade_returns_remaining(isolated_home: Path) -> None:
    config = ArgosConfig.load()
    config.limits["facebook"] = PlatformLimits(per_minute=600, daily_actions=5)
    clock = FakeClock()
    limiter = RateLimiter(config, "facebook", sleep_fn=clock.sleep)

    assert limiter.before_action() == 4
    assert limiter.before_action() == 3
    assert limiter.daily_remaining() == 3
