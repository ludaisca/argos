"""Investigación multi-objetivo: corre varios flujos (Instagram + Facebook) y arma el informe.

Un plan YAML lista objetivos; la corrida agrupa por plataforma (una sola sesión
por red, más humano y más barato), respeta los mismos límites/pacing que el CLI,
y al final genera ``report.md`` / CSV / ``argos.db`` en la carpeta del job.
"""

from __future__ import annotations

import datetime as dt
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from playwright.sync_api import Error as PlaywrightError
from rich.console import Console

from argos.browser.limiter import RateLimiter
from argos.browser.pacing import Pacer
from argos.browser.session import BrowserSession
from argos.config import ArgosConfig
from argos.errors import ArgosError, NeedsHumanError, RateLimitedError, UsageError
from argos.report import DATASETS, build_report
from argos.store import append_unique_jsonl

_console = Console(stderr=True)

TARGET_PLATFORM: dict[str, str] = {
    "ig_profile": "instagram",
    "ig_posts": "instagram",
    "ig_hashtag": "instagram",
    "ig_reels": "instagram",
    "ig_search": "instagram",
    "ig_comments": "instagram",
    "fb_page": "facebook",
    "fb_search": "facebook",
    "fb_groups_feed": "facebook",
    "places_search": "places",
}

EXAMPLE_PLAN = """\
job: "Ejemplo de investigación"
headless: true
targets:
  - type: ig_profile
    value: nasa
    limit: 12
  - type: ig_hashtag
    value: astrophotography
    limit: 12
    details: true
  - type: fb_page
    value: NASA
    limit: 10
  - type: places_search
    value: cafeterías
    kind: Puebla, MX
    limit: 20
"""


@dataclass
class Target:
    type: str
    value: str | None = None
    limit: int = 12
    details: bool = False
    kind: str | None = None
    variants: bool = False
    since: str | None = None

    @property
    def platform(self) -> str:
        return TARGET_PLATFORM[self.type]

    def label(self) -> str:
        return f"{self.type}:{self.value or ''}"


def parse_targets(targets_raw: object) -> list[Target]:
    """Valida y normaliza una lista de targets (de un plan o de un LLM)."""
    if not isinstance(targets_raw, list) or not targets_raw:
        raise UsageError("el plan necesita una lista `targets` no vacía")
    targets: list[Target] = []
    for index, item in enumerate(targets_raw, 1):
        if not isinstance(item, dict):
            raise UsageError(f"target #{index} debe ser un objeto")
        ttype = str(item.get("type") or "")
        if ttype not in TARGET_PLATFORM:
            raise UsageError(
                f"target #{index}: tipo desconocido {ttype!r}",
                hint=f"opciones: {', '.join(TARGET_PLATFORM)}",
            )
        if ttype != "fb_groups_feed" and not item.get("value"):
            raise UsageError(f"target #{index} ({ttype}) necesita `value`")
        try:
            limit = int(item.get("limit") or 12)
        except (TypeError, ValueError):
            limit = 12
        targets.append(
            Target(
                type=ttype,
                value=str(item["value"]) if item.get("value") is not None else None,
                limit=limit,
                details=bool(item.get("details")),
                kind=str(item["kind"]) if item.get("kind") else None,
                variants=bool(item.get("variants")),
                since=str(item["since"]) if item.get("since") else None,
            )
        )
    return targets


def load_plan(path: Path) -> tuple[str, bool, list[Target]]:
    """Lee y valida el plan YAML; devuelve ``(job, headless, targets)``."""
    try:
        raw = Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        raise UsageError(f"no se pudo leer el plan: {exc}") from exc
    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise UsageError(f"plan YAML inválido: {exc}") from exc
    if not isinstance(data, dict):
        raise UsageError("el plan debe ser un objeto YAML con una lista `targets`")
    targets = parse_targets(data.get("targets"))
    return str(data.get("job") or "research"), bool(data.get("headless", True)), targets


def _execute(
    session: BrowserSession,
    target: Target,
    *,
    limiter: RateLimiter,
    pacer: Pacer,
) -> tuple[dict[str, list[Any]], int, int]:
    """Corre un target y devuelve ``(registros por dataset, acciones, cuota restante)``."""
    from argos.platforms import facebook as fb
    from argos.platforms import instagram as ig

    value = target.value or ""
    since = ig.parse_since(target.since) if target.since else None

    if target.type == "ig_profile":
        profile_result = ig.fetch_profile(
            session, value, limiter=limiter, pacer=pacer, limit=target.limit
        )
        return (
            {"profiles": [profile_result.profile], "posts": list(profile_result.recent_posts)},
            profile_result.actions,
            profile_result.daily_remaining,
        )
    if target.type == "ig_posts":
        posts_result = ig.fetch_posts(
            session, value, limiter=limiter, pacer=pacer,
            limit=target.limit, details=target.details, since=since,
        )
        return (
            {"posts": list(posts_result.posts)},
            posts_result.actions,
            posts_result.daily_remaining,
        )
    if target.type == "ig_hashtag":
        hashtag_result = ig.fetch_hashtag(
            session, value, limiter=limiter, pacer=pacer,
            limit=target.limit, details=target.details, since=since,
        )
        return (
            {"posts": list(hashtag_result.posts)},
            hashtag_result.actions,
            hashtag_result.daily_remaining,
        )
    if target.type == "ig_reels":
        reels_result = ig.fetch_reels(
            session, value, limiter=limiter, pacer=pacer,
            limit=target.limit, details=target.details, since=since,
        )
        return (
            {"posts": list(reels_result.posts)},
            reels_result.actions,
            reels_result.daily_remaining,
        )
    if target.type == "ig_search":
        ig_search_result = ig.search(
            session, value, limiter=limiter, pacer=pacer,
            kind=target.kind or "posts", limit=target.limit, variants=target.variants,
        )
        return (
            {"posts": list(ig_search_result.posts), "search": list(ig_search_result.hits)},
            ig_search_result.actions,
            ig_search_result.daily_remaining,
        )
    if target.type == "ig_comments":
        comments_result = ig.fetch_comments(
            session, value, limiter=limiter, pacer=pacer, limit=target.limit
        )
        return (
            {"comments": list(comments_result.comments)},
            comments_result.actions,
            comments_result.daily_remaining,
        )
    if target.type == "fb_page":
        page_result = fb.fetch_page(
            session, value, limiter=limiter, pacer=pacer, limit=target.limit
        )
        return (
            {"profiles": [page_result.profile], "posts": list(page_result.posts)},
            page_result.actions,
            page_result.daily_remaining,
        )
    if target.type == "fb_search":
        fb_search_result = fb.search(
            session, value, limiter=limiter, pacer=pacer,
            kind=target.kind or "pages", limit=target.limit, variants=target.variants,
        )
        return (
            {"search": list(fb_search_result.hits)},
            fb_search_result.actions,
            fb_search_result.daily_remaining,
        )

    # fb_groups_feed
    feed_result = fb.fetch_group_feed(session, limiter=limiter, pacer=pacer, limit=target.limit)
    return {"posts": list(feed_result.posts)}, feed_result.actions, feed_result.daily_remaining


def _execute_places(
    target: Target, *, config: ArgosConfig
) -> tuple[dict[str, list[Any]], int, int]:
    """Búsqueda de lugares: OpenStreetMap por defecto; Google Maps si ``details: true``."""
    from argos import places as places_mod

    result = places_mod.search(
        target.value or "",
        location=target.kind,
        limit=target.limit,
        provider="gmaps" if target.details else "osm",
        config=config,
        headless=True,
    )
    limiter = RateLimiter(config, "places")
    charged = 0
    for _ in range(max(1, result.actions)):
        limiter.before_action()
        charged += 1
    return {"places": list(result.places)}, charged, limiter.daily_remaining()


def _slug(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-")[:40] or "research"


def run_research(
    plan_path: Path,
    *,
    base_dir: Path,
    headless: bool | None = None,
    config: ArgosConfig | None = None,
) -> dict[str, Any]:
    """Ejecuta el plan y devuelve ``{job_dir, results, report}``."""
    job, plan_headless, targets = load_plan(plan_path)
    effective_headless = plan_headless if headless is None else headless
    config = config or ArgosConfig.load()

    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    job_dir = Path(base_dir) / f"{_slug(job)}-{stamp}"
    job_dir.mkdir(parents=True, exist_ok=True)

    by_platform: dict[str, list[Target]] = {}
    for target in targets:
        by_platform.setdefault(target.platform, []).append(target)

    results: list[dict[str, Any]] = []

    def _record(
        target: Target, records: dict[str, list[Any]], actions: int, remaining: int
    ) -> None:
        written: dict[str, int] = {}
        for name, models in records.items():
            if not models:
                continue
            filename, keys = DATASETS[name]
            written[name], _skipped = append_unique_jsonl(
                job_dir / filename, models, keys
            )
        results.append(
            {"target": target.label(), "status": "ok", "written": written,
             "actions": actions, "daily_remaining": remaining}
        )

    for platform, platform_targets in by_platform.items():
        if platform == "places":
            for target in platform_targets:
                _console.print(f"[dim]→ {target.label()}[/dim]")
                try:
                    records, actions, remaining = _execute_places(target, config=config)
                except (NeedsHumanError, RateLimitedError) as exc:
                    results.append(
                        {"target": target.label(), "status": "stopped", "detail": str(exc)}
                    )
                    continue
                except ArgosError as exc:
                    results.append(
                        {"target": target.label(), "status": "error", "detail": str(exc)}
                    )
                    continue
                _record(target, records, actions, remaining)
            continue

        limiter = RateLimiter(config, platform)
        pacer = Pacer()
        stopped = False
        try:
            with BrowserSession(platform, config, headless=effective_headless) as session:
                for target in platform_targets:
                    if stopped:
                        results.append(
                            {"target": target.label(), "status": "skipped",
                             "detail": "plataforma detenida por límite/verificación"}
                        )
                        continue
                    _console.print(f"[dim]→ {target.label()}[/dim]")
                    try:
                        records, actions, remaining = _execute(
                            session, target, limiter=limiter, pacer=pacer
                        )
                    except (NeedsHumanError, RateLimitedError) as exc:
                        results.append(
                            {"target": target.label(), "status": "stopped", "detail": str(exc)}
                        )
                        stopped = True
                        continue
                    except ArgosError as exc:
                        results.append(
                            {"target": target.label(), "status": "error", "detail": str(exc)}
                        )
                        continue
                    _record(target, records, actions, remaining)
        except PlaywrightError as exc:
            results.append(
                {"target": f"platform:{platform}", "status": "error",
                 "detail": f"falló el navegador: {exc}"}
            )

    manifest = {
        "job": job,
        "generated_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "headless": effective_headless,
        "results": results,
    }
    (job_dir / "run.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    report: dict[str, Any] | None
    try:
        report = build_report(job_dir, title=job)
    except UsageError:
        report = None
    return {"job_dir": str(job_dir), "results": results, "report": report}
