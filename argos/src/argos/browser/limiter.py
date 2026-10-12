"""Límites de velocidad: token bucket por proceso + cuota diaria persistida."""

from __future__ import annotations

import datetime as dt
import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from argos.config import ArgosConfig
from argos.errors import RateLimitedError
from argos.private_fs import (
    PrivatePathError,
    atomic_write_private_text,
    read_small_text_no_follow,
)

_MAX_STATE_BYTES = 256 * 1024
_KEEP_DAYS = 7


def _local_day() -> str:
    return dt.datetime.now().strftime("%Y-%m-%d")


@dataclass
class TokenBucket:
    """Bucket clásico; ``time_fn``/``sleep_fn`` inyectables para tests."""

    rate_per_minute: float
    capacity: float | None = None
    time_fn: Callable[[], float] = time.monotonic
    sleep_fn: Callable[[float], None] = time.sleep
    _tokens: float = field(init=False, repr=False)
    _updated: float = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if self.rate_per_minute <= 0:
            raise ValueError("rate_per_minute debe ser > 0")
        capacity = self.capacity if self.capacity is not None else self.rate_per_minute
        if capacity <= 0:
            raise ValueError("capacity debe ser > 0")
        self.capacity = float(capacity)
        self._tokens = self.capacity
        self._updated = self.time_fn()

    def _refill(self) -> None:
        now = self.time_fn()
        elapsed = now - self._updated
        if elapsed <= 0:
            return
        self._tokens = min(
            self.capacity or 0.0,
            self._tokens + elapsed * self.rate_per_minute / 60.0,
        )
        self._updated = now

    def try_acquire(self, tokens: float = 1.0) -> bool:
        if self.capacity is not None and tokens > self.capacity:
            raise ValueError("tokens no puede superar capacity")
        self._refill()
        if self._tokens >= tokens:
            self._tokens -= tokens
            return True
        return False

    def wait_time(self, tokens: float = 1.0) -> float:
        self._refill()
        deficit = tokens - self._tokens
        if deficit <= 0:
            return 0.0
        return deficit * 60.0 / self.rate_per_minute

    def acquire(self, tokens: float = 1.0) -> None:
        while not self.try_acquire(tokens):
            self.sleep_fn(self.wait_time(tokens))


class DailyQuota:
    """Contador diario persistido en ``state/limits.json``."""

    def __init__(
        self,
        state_path: Path,
        platform: str,
        daily_limit: int,
        *,
        day_fn: Callable[[], str] | None = None,
    ) -> None:
        self._path = state_path
        self._platform = platform
        self._limit = daily_limit
        self._day_fn = day_fn or _local_day

    def used(self) -> int:
        days = self._load().get("days", {})
        if not isinstance(days, dict):
            return 0
        today = days.get(self._day_fn(), {})
        if not isinstance(today, dict):
            return 0
        value = today.get(self._platform, 0)
        return int(value) if isinstance(value, int) else 0

    def remaining(self) -> int:
        return max(0, self._limit - self.used())

    def consume(self, n: int = 1) -> int:
        """Suma ``n`` acciones y devuelve el remanente; falla si excede la cuota."""
        data = self._load()
        days = data.get("days", {})
        if not isinstance(days, dict):
            days = {}
        today = self._day_fn()
        day = days.get(today, {})
        if not isinstance(day, dict):
            day = {}
        current = day.get(self._platform, 0)
        used = current if isinstance(current, int) else 0
        if used + n > self._limit:
            raise RateLimitedError(
                f"cuota diaria agotada para {self._platform} ({used}/{self._limit})",
                hint=(
                    "volvé a intentar mañana o subí "
                    f"`limits.{self._platform}.daily_actions` en la configuración"
                ),
            )
        day[self._platform] = used + n
        days[today] = day
        self._save({"days": _prune_days(days, today)})
        return self._limit - used - n

    def _load(self) -> dict[str, Any]:
        try:
            raw = read_small_text_no_follow(self._path, max_bytes=_MAX_STATE_BYTES)
        except (PrivatePathError, OSError, UnicodeError):
            return {}
        if raw is None:
            return {}
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        return data if isinstance(data, dict) else {}

    def _save(self, payload: dict[str, Any]) -> None:
        atomic_write_private_text(
            self._path,
            json.dumps(payload, ensure_ascii=False, indent=2),
        )


def _prune_days(days: dict[str, Any], today: str) -> dict[str, Any]:
    try:
        cutoff = (dt.date.fromisoformat(today) - dt.timedelta(days=_KEEP_DAYS)).isoformat()
    except ValueError:
        return days
    return {
        day: value
        for day, value in days.items()
        if isinstance(day, str) and day >= cutoff
    }


class RateLimiter:
    """Fachada por plataforma: consume cuota y espera el turno del bucket."""

    def __init__(
        self,
        config: ArgosConfig,
        platform: str,
        *,
        sleep_fn: Callable[[float], None] = time.sleep,
    ) -> None:
        limits = config.limits_for(platform)
        self._bucket = TokenBucket(
            rate_per_minute=limits.per_minute,
            sleep_fn=sleep_fn,
        )
        self._quota = DailyQuota(
            config.state_dir() / "limits.json",
            platform,
            limits.daily_actions,
        )

    def before_action(self) -> int:
        """Debe llamarse antes de cada acción de red; devuelve el remanente diario."""
        remaining = self._quota.consume()
        self._bucket.acquire()
        return remaining

    def daily_remaining(self) -> int:
        return self._quota.remaining()
