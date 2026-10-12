"""Agente autónomo: brief → plan (LLM) → recolección → análisis (LLM) → informe.

Pensado para Docker: se configura por variables de entorno y ejecuta ciclos de
investigación (una corrida con ``agent run`` o un loop con ``agent daemon``).

Variables de entorno:
  ARGOS_LLM_API_KEY / ARGOS_LLM_BASE_URL / ARGOS_LLM_MODEL   (LLM)
  ARGOS_BRIEF_FILE  o  ARGOS_BRIEF                            (objetivo)
  ARGOS_COOKIES_IG / ARGOS_COOKIES_FB                         (sesiones)
  ARGOS_INTERVAL_HOURS                                        (cadencia del daemon)
  ARGOS_WEBHOOK_URL                                           (aviso opcional)
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import requests
import yaml
from rich.console import Console

from argos.config import ArgosConfig
from argos.errors import ArgosError, UsageError
from argos.llm import LLMError, LLMSettings, chat, parse_json_response
from argos.report import load_datasets
from argos.research import TARGET_PLATFORM, Target, parse_targets, run_research

_console = Console(stderr=True)

MAX_TARGETS = 6
TARGET_LIMIT_CAP = 20
MAX_CONTEXT_CHARS = 14_000

PLANNER_SYSTEM = (
    "Sos un planificador de investigación en redes sociales. "
    "Devolvés SOLO un objeto JSON válido, sin texto extra."
)
PLANNER_USER = """\
Objetivo: {objective}
Preguntas: {questions}
Tipos de target permitidos: {types}
Reglas:
- Máximo {max_targets} targets, los más útiles para el objetivo.
- `limit` <= {limit_cap} por target.
- `value` es usuario/etiqueta/término (URL de post solo para ig_comments).
- Para ig_search usá "kind": "posts" o "users".
- Para fb_search usá "kind": "pages" | "groups" | "people".
- Formato exacto: {{"targets": [{{"type": "...", "value": "...", "limit": 12}}]}}
"""

ANALYST_SYSTEM = (
    "Sos un analista de investigación. Escribís en Markdown, en español, claro y concreto. "
    "Usás SOLO los datos provistos; si un dato falta lo decís. No inventás métricas ni cuentas."
)
ANALYST_USER = """\
OBJETIVO: {objective}

PREGUNTAS:
{questions}

DATOS RECOLECTADOS:
{context}

Escribí el informe en Markdown con estas secciones:
## Resumen ejecutivo
## Hallazgos por pregunta
## Actores y temas clave
## Datos que faltan o próximos pasos
"""


@dataclass
class Brief:
    name: str = "research"
    objective: str = ""
    questions: list[str] = field(default_factory=list)
    targets: list[dict[str, Any]] = field(default_factory=list)
    max_targets: int = MAX_TARGETS


@dataclass
class AgentRunResult:
    run_dir: Path
    plan: list[dict[str, Any]]
    plan_source: str
    job_dir: str | None = None
    analysis_path: Path | None = None
    results: list[dict[str, Any]] = field(default_factory=list)


# --------------------------------------------------------------------------- #
# Configuración (archivo / entorno)
# --------------------------------------------------------------------------- #


def resolve_brief(brief_path: str | None = None) -> Brief:
    """Brief desde un archivo explícito, ``ARGOS_BRIEF_FILE`` o ``ARGOS_BRIEF``."""
    if brief_path:
        return load_brief(path=Path(brief_path))
    env_file = os.environ.get("ARGOS_BRIEF_FILE")
    if env_file:
        return load_brief(path=Path(env_file))
    env_text = os.environ.get("ARGOS_BRIEF")
    if env_text:
        return load_brief(text=env_text)
    raise UsageError(
        "falta el brief",
        hint="pasá --brief archivo.yaml o definí ARGOS_BRIEF / ARGOS_BRIEF_FILE",
    )


def load_brief(*, path: Path | None = None, text: str | None = None) -> Brief:
    """Carga el brief desde un YAML o desde texto libre (entorno)."""
    data: dict[str, Any] = {}
    if path is not None:
        try:
            raw = Path(path).read_text(encoding="utf-8")
        except OSError as exc:
            raise UsageError(f"no se pudo leer el brief: {exc}") from exc
        loaded = yaml.safe_load(raw)
        if not isinstance(loaded, dict):
            raise UsageError("el brief debe ser un objeto YAML")
        data = loaded
    if text:
        data.setdefault("objective", text)

    objective = str(data.get("objective") or data.get("brief") or "").strip()
    if not objective:
        raise UsageError(
            "el brief necesita un `objective`",
            hint="en el YAML poné `objective: ...` o definí ARGOS_BRIEF",
        )
    questions_raw = data.get("questions") or []
    questions = [str(item) for item in questions_raw] if isinstance(questions_raw, list) else []
    targets_raw = data.get("targets") or []
    targets = (
        [item for item in targets_raw if isinstance(item, dict)]
        if isinstance(targets_raw, list)
        else []
    )
    try:
        max_targets = int(data.get("max_targets") or MAX_TARGETS)
    except (TypeError, ValueError):
        max_targets = MAX_TARGETS
    return Brief(
        name=str(data.get("job") or "research"),
        objective=objective,
        questions=questions,
        targets=targets,
        max_targets=max(1, min(max_targets, 12)),
    )


def apply_env_cookies(config: ArgosConfig) -> list[str]:
    """Importa cookies desde ``ARGOS_COOKIES_DIR`` o ``ARGOS_COOKIES_IG``/``ARGOS_COOKIES_FB``."""
    from argos.cookies import CONFIG_KEYS, parse_cookie_input

    sources: list[tuple[str, str, str]] = []  # (etiqueta, raw, plataforma)
    cookie_dir = os.environ.get("ARGOS_COOKIES_DIR")
    if cookie_dir and Path(cookie_dir).is_dir():
        for platform in ("instagram", "facebook"):
            candidate = Path(cookie_dir) / f"{platform}-cookies.json"
            if candidate.is_file():
                sources.append((str(candidate), candidate.read_text(encoding="utf-8"), platform))
    for env_name, platform in (
        ("ARGOS_COOKIES_IG", "instagram"),
        ("ARGOS_COOKIES_FB", "facebook"),
    ):
        raw = os.environ.get(env_name)
        if raw:
            sources.append((env_name, raw, platform))

    imported: list[str] = []
    for label, raw, platform in sources:
        try:
            cookies = parse_cookie_input(raw, platform)
        except ValueError as exc:
            _console.print(f"[yellow]{label}: {exc}[/yellow]")
            continue
        if cookies:
            config.set(CONFIG_KEYS[platform], cookies)
            if platform not in imported:
                imported.append(platform)
    return imported


# --------------------------------------------------------------------------- #
# Planificación y análisis (LLM)
# --------------------------------------------------------------------------- #


def plan_targets(settings: LLMSettings, brief: Brief) -> list[dict[str, Any]]:
    """Pide al LLM un plan de targets, lo valida y lo acota."""
    prompt = PLANNER_USER.format(
        objective=brief.objective,
        questions="; ".join(brief.questions) or "(ninguna en particular)",
        types=", ".join(TARGET_PLATFORM),
        max_targets=brief.max_targets,
        limit_cap=TARGET_LIMIT_CAP,
    )
    content = chat(
        settings,
        [
            {"role": "system", "content": PLANNER_SYSTEM},
            {"role": "user", "content": prompt},
        ],
        json_mode=True,
    )
    data = parse_json_response(content)
    if not isinstance(data, dict) or not isinstance(data.get("targets"), list):
        raise LLMError("el plan del LLM no tiene una lista `targets`")
    try:
        parsed: list[Target] = parse_targets(data["targets"][: brief.max_targets])
    except UsageError as exc:
        raise LLMError(f"el plan del LLM no es válido: {exc}") from exc

    plan: list[dict[str, Any]] = []
    for target in parsed:
        item: dict[str, Any] = {
            "type": target.type,
            "limit": max(1, min(target.limit, TARGET_LIMIT_CAP)),
        }
        if target.value:
            item["value"] = target.value
        if target.kind:
            item["kind"] = target.kind
        if target.details:
            item["details"] = True
        if target.since:
            item["since"] = target.since
        plan.append(item)
    return plan


def build_context(job_dir: Path, *, max_posts: int = 40, max_comments: int = 30) -> str:
    """Resumen compacto y acotado de los datos recolectados, para el LLM."""
    datasets = load_datasets(job_dir)
    lines: list[str] = []

    profiles = datasets.get("profiles", [])
    if profiles:
        lines.append("PERFILES:")
        for record in profiles[:20]:
            lines.append(
                f"- @{record.get('username')} | {record.get('full_name') or ''} | "
                f"{record.get('followers')} seguidores | {(record.get('bio') or '')[:120]}"
            )

    posts = sorted(datasets.get("posts", []), key=lambda row: row.get("likes") or 0, reverse=True)
    if posts:
        lines.append("POSTS (ordenados por likes):")
        for record in posts[:max_posts]:
            caption = (record.get("caption") or "").replace("\n", " ")[:200]
            date = str(record.get("created_at") or "")[:10] or "s/f"
            lines.append(
                f"- [{record.get('platform')}] {date} | @{record.get('author')} | "
                f"{record.get('likes')} likes · {record.get('comments')} comentarios | "
                f"{caption} | {record.get('url')}"
            )

    comments = datasets.get("comments", [])
    if comments:
        lines.append("COMENTARIOS:")
        for record in comments[:max_comments]:
            text = (record.get("text") or "").replace("\n", " ")[:140]
            lines.append(f"- @{record.get('author')}: {text}")

    hits = datasets.get("search", [])
    if hits:
        lines.append("RESULTADOS DE BÚSQUEDA:")
        for record in hits[:20]:
            lines.append(
                f"- [{record.get('type')}] {record.get('name')} | "
                f"{record.get('followers')} seguidores | {record.get('url')}"
            )

    return "\n".join(lines)[:MAX_CONTEXT_CHARS]


def analyze(settings: LLMSettings, brief: Brief, context: str) -> str:
    content = chat(
        settings,
        [
            {"role": "system", "content": ANALYST_SYSTEM},
            {
                "role": "user",
                "content": ANALYST_USER.format(
                    objective=brief.objective,
                    questions="\n".join(f"- {q}" for q in brief.questions)
                    or "(ninguna en particular)",
                    context=context or "(sin datos)",
                ),
            },
        ],
        timeout=180,
    )
    return content.strip() + "\n"


def notify(webhook_url: str, text: str, analysis_path: Path | None = None) -> bool:
    """Aviso opcional por webhook (n8n, Slack, Telegram…)."""
    payload: dict[str, Any] = {"text": text}
    if analysis_path is not None and analysis_path.exists():
        payload["analysis"] = analysis_path.read_text(encoding="utf-8")[:8000]
    try:
        response = requests.post(webhook_url, json=payload, timeout=15)
        return response.ok
    except requests.RequestException:
        return False


# --------------------------------------------------------------------------- #
# Ciclos
# --------------------------------------------------------------------------- #


def _slug(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-")[:40] or "run"


def run_once(
    config: ArgosConfig,
    *,
    brief: Brief,
    base_dir: Path,
    settings: LLMSettings,
    webhook_url: str | None = None,
) -> AgentRunResult:
    """Un ciclo completo: plan → recolección → análisis → informe."""
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    run_dir = Path(base_dir) / f"{_slug(brief.name)}-{stamp}"
    run_dir.mkdir(parents=True, exist_ok=True)

    if brief.targets:
        plan = brief.targets
        plan_source = "brief"
    else:
        _console.print("[dim]planificando con el LLM…[/dim]")
        plan = plan_targets(settings, brief)
        plan_source = "llm"
    if not plan:
        raise ArgosError("el plan quedó vacío (revisá el brief)")

    plan_data = {"job": brief.name, "headless": True, "targets": plan}
    plan_path = run_dir / "plan.yaml"
    plan_path.write_text(
        yaml.safe_dump(plan_data, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )

    research_result = run_research(plan_path, base_dir=run_dir / "data", config=config)
    job_dir = research_result.get("job_dir")

    analysis_path: Path | None = None
    if job_dir:
        context = build_context(Path(str(job_dir)))
        if context:
            _console.print("[dim]analizando con el LLM…[/dim]")
            analysis_path = run_dir / "analysis.md"
            analysis_path.write_text(analyze(settings, brief, context), encoding="utf-8")

    result = AgentRunResult(
        run_dir=run_dir,
        plan=plan,
        plan_source=plan_source,
        job_dir=str(job_dir) if job_dir else None,
        analysis_path=analysis_path,
        results=list(research_result.get("results") or []),
    )
    (run_dir / "run.json").write_text(
        json.dumps(
            {
                "job": brief.name,
                "objective": brief.objective,
                "generated_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
                "plan_source": plan_source,
                "plan": plan,
                "job_dir": result.job_dir,
                "analysis": str(analysis_path) if analysis_path else None,
                "results": result.results,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    if webhook_url:
        ok = sum(1 for item in result.results if item.get("status") == "ok")
        notify(webhook_url, f"Argos: «{brief.name}» — {ok} objetivos ok", analysis_path)

    return result


def run_daemon(
    config: ArgosConfig,
    *,
    brief: Brief,
    base_dir: Path,
    settings: LLMSettings,
    interval_hours: float,
    max_runs: int | None = None,
    webhook_url: str | None = None,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> list[AgentRunResult]:
    """Loop de ciclos con cadencia (para el contenedor del VPS)."""
    runs: list[AgentRunResult] = []
    count = 0
    while max_runs is None or count < max_runs:
        count += 1
        _console.print(f"[bold]ciclo {count}[/bold]")
        try:
            runs.append(
                run_once(
                    config,
                    brief=brief,
                    base_dir=base_dir,
                    settings=settings,
                    webhook_url=webhook_url,
                )
            )
        except ArgosError as exc:
            _console.print(f"[red]ciclo {count} falló:[/red] {exc}")
        if max_runs is not None and count >= max_runs:
            break
        sleep_fn(max(60.0, interval_hours * 3600))
    return runs
