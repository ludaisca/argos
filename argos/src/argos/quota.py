"""Reporte de cuota diaria, sin navegador (para gatear antes de correr)."""

from __future__ import annotations

from typing import Any

from argos.browser.limiter import DailyQuota
from argos.config import ArgosConfig

_PLATFORMS = ("instagram", "facebook", "youtube", "linkedin", "x")


def quota_report(config: ArgosConfig | None = None, platform: str | None = None) -> dict[str, Any]:
    """Uso/restante de la cuota diaria por plataforma.

    Devuelve un dict serializable, pensado para ``argos quota --json`` y para
    que agentes o workflows decidan si seguir antes de lanzar un comando.
    """
    config = config or ArgosConfig.load()
    names = (platform,) if platform else _PLATFORMS
    report: dict[str, Any] = {}
    for name in names:
        limits = config.limits_for(name)
        quota = DailyQuota(
            config.state_dir() / "limits.json",
            name,
            limits.daily_actions,
        )
        report[name] = {
            "used": quota.used(),
            "daily_limit": limits.daily_actions,
            "remaining": quota.remaining(),
            "per_minute": limits.per_minute,
        }
    return report
