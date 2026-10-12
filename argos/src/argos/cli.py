"""CLI de Argos."""

from __future__ import annotations

import contextlib
import functools
import json
import os
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import typer
from playwright.sync_api import Error as PlaywrightError
from rich.console import Console
from rich.table import Table

from argos import __version__
from argos.browser.limiter import RateLimiter
from argos.browser.pacing import Pacer
from argos.browser.session import BrowserSession
from argos.config import ArgosConfig
from argos.doctor import collect
from argos.errors import ArgosError, LoginRequiredError, UsageError
from argos.formatting import compact_number
from argos.models import Post
from argos.platforms import get_platform
from argos.platforms.base import PlatformStatus, run_login
from argos.platforms.facebook import (
    fetch_group_feed,
    fetch_page,
)
from argos.platforms.facebook import search as fb_search
from argos.platforms.instagram import (
    MAX_COMMENTS_LIMIT,
    MAX_POSTS_LIMIT,
    PostsResult,
    fetch_comments,
    fetch_hashtag,
    fetch_posts,
    fetch_profile,
    fetch_reels,
    parse_since,
    search,
)
from argos.quota import quota_report
from argos.store import append_unique_jsonl

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="Investigación de Facebook e Instagram con Playwright.",
)
console = Console()
err_console = Console(stderr=True)


def _guard(fn: Callable[..., Any]) -> Callable[..., Any]:
    """Muestra errores tipados sin traceback y traduce su exit code."""

    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return fn(*args, **kwargs)
        except ArgosError as exc:
            err_console.print(f"[red]error:[/red] {exc}")
            if exc.hint:
                err_console.print(f"[yellow]hint:[/yellow] {exc.hint}")
            raise typer.Exit(code=exc.exit_code) from None
        except PlaywrightError as exc:
            # Red de seguridad: el navegador se cerró o murió en medio de un comando.
            err_console.print(
                f"[red]error:[/red] el navegador se cerró o falló inesperadamente: {exc}"
            )
            err_console.print(
                "[yellow]hint:[/yellow] reintentá el comando; si persiste, "
                "corré `argos doctor`"
            )
            raise typer.Exit(code=1) from None

    return wrapper


def _version_callback(value: bool) -> bool:
    if value:
        typer.echo(f"argos {__version__}")
        raise typer.Exit()
    return value


@app.callback()
def main_callback(
    version: bool = typer.Option(
        False,
        "--version",
        "-V",
        callback=_version_callback,
        is_eager=True,
        help="Mostrar la versión y salir.",
    ),
) -> None:
    """Argos: navegá e investigá Facebook e Instagram con Playwright."""


_STATUS_STYLE: dict[str, str] = {
    "ok": "green",
    "needs-login": "yellow",
    "checkpoint": "yellow",
    "rate-limited": "yellow",
    "off": "red",
    "error": "red",
}


@app.command()
@_guard
def quota(
    json_output: bool = typer.Option(False, "--json", help="Salida JSON (contrato de agentes)."),
    platform: str = typer.Option(
        None, "--platform", help="Limitar a una plataforma (instagram|facebook)."
    ),
) -> None:
    """Cuánta cuota diaria queda (sin abrir navegador)."""
    report = quota_report(platform=platform)

    if json_output:
        typer.echo(json.dumps(report, ensure_ascii=False, indent=2))
        return

    table = Table(show_header=True, header_style="bold")
    table.add_column("plataforma")
    table.add_column("usado", justify="right")
    table.add_column("límite", justify="right")
    table.add_column("restante", justify="right")
    table.add_column("por minuto", justify="right")
    for name, entry in report.items():
        table.add_row(
            name,
            str(entry["used"]),
            str(entry["daily_limit"]),
            str(entry["remaining"]),
            str(entry["per_minute"]),
        )
    console.print(table)


@app.command()
@_guard
def skill(
    install: bool = typer.Option(
        False, "--install", help="Instalar SKILL.md en los directorios de skills detectados."
    ),
    uninstall: bool = typer.Option(
        False, "--uninstall", help="Quitar los SKILL.md instalados."
    ),
    path_only: bool = typer.Option(
        False, "--path", help="Imprimir la ruta del SKILL.md incluido."
    ),
) -> None:
    """Gestiona el skill (instructivo para agentes) de Argos."""
    from argos.skill_install import (
        install_skill,
        packaged_skill_path,
        packaged_skill_text,
        skill_targets,
        uninstall_skill,
    )

    if path_only:
        typer.echo(str(packaged_skill_path()))
        return
    if install:
        written = install_skill(skill_targets(), packaged_skill_text())
        for path in written:
            err_console.print(f"[dim]instalado: {path}[/dim]")
        console.print(f"[green]ok[/green] SKILL.md instalado en {len(written)} directorios")
        return
    if uninstall:
        removed = uninstall_skill(skill_targets())
        for path in removed:
            err_console.print(f"[dim]quitado: {path}[/dim]")
        console.print(f"[green]ok[/green] {len(removed)} SKILL.md quitados")
        return
    typer.echo("usá --install, --uninstall o --path")


@app.command()
@_guard
def mcp() -> None:
    """Arranca el servidor MCP (stdio) para agentes y n8n."""
    from argos.mcp_server import run

    run()


@app.command()
@_guard
def doctor(
    json_output: bool = typer.Option(False, "--json", help="Salida JSON (contrato para agentes)."),
    platform: list[str] = typer.Option(
        [],
        "--platform",
        help="Limitar el chequeo a una plataforma (repetible).",
    ),
    headed: bool = typer.Option(
        False,
        "--headed",
        help="Abrir el navegador con ventana (por defecto: headless).",
    ),
) -> None:
    """Chequea navegador, sesiones y estado de cada plataforma."""
    config = ArgosConfig.load()
    data = collect(config, platforms=platform or None, headless=not headed)

    if json_output:
        typer.echo(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        browser_state = "ok" if data["browser"]["ready"] else "faltante"
        console.print(
            f"[bold]Argos doctor[/bold] — navegador: {browser_state} "
            f"({data['browser']['detail']})"
        )
        table = Table(show_header=True, header_style="bold")
        table.add_column("plataforma")
        table.add_column("estado")
        table.add_column("detalle")
        table.add_column("pista")
        for name, entry in data["platforms"].items():
            status = str(entry["status"])
            style = _STATUS_STYLE.get(status, "white")
            table.add_row(
                name,
                f"[{style}]{status}[/{style}]",
                str(entry["detail"]),
                str(entry["hint"] or ""),
            )
        console.print(table)

    broken = [
        name
        for name, entry in data["platforms"].items()
        if entry["status"] not in {"ok", "needs-login"}
    ]
    if broken or not data["browser"]["ready"]:
        raise typer.Exit(code=1)


@app.command()
@_guard
def login(
    platform: str = typer.Argument(..., help="instagram | facebook"),
    timeout: int = typer.Option(
        600, "--timeout", help="Segundos máximos de espera del login humano."
    ),
    proxy: str = typer.Option(
        None, "--proxy", help="Proxy para esta sesión (http://user:pass@host:port)."
    ),
) -> None:
    """Abre el navegador para iniciar sesión a mano y verifica la sesión."""
    target = get_platform(platform)
    config = ArgosConfig.load()
    status: PlatformStatus = run_login(target, config, timeout_s=timeout, proxy=proxy)
    if status.status != "ok":
        raise LoginRequiredError(status.detail, hint=status.hint)
    console.print(f"[green]ok[/green] {status.detail}")


@app.command()
@_guard
def configure(
    key: str = typer.Argument(..., help="ig-cookies | fb-cookies"),
    read_stdin: bool = typer.Option(
        False, "--stdin", help="Leer el JSON/header desde stdin (no lo deja en el historial)."
    ),
    value: str = typer.Option(
        None, "--value", help="Valor en línea (queda en el historial; preferí --stdin)."
    ),
) -> None:
    """Importa cookies de tu propia sesión (Cookie-Editor) para usar Argos sin navegador."""
    from argos.cookies import CONFIG_KEYS, PLATFORM_BY_KEY, parse_cookie_input

    platform = PLATFORM_BY_KEY.get(key)
    if platform is None:
        raise UsageError(f"clave desconocida: {key!r}", hint="opciones: ig-cookies, fb-cookies")
    if read_stdin and value:
        raise UsageError("--stdin y --value no se pueden combinar")
    if read_stdin:
        raw = sys.stdin.read(1_048_576)
    elif value:
        err_console.print(
            "[yellow]aviso:[/yellow] el valor por línea queda en el historial de shell"
        )
        raw = value
    else:
        raw = typer.prompt(
            "Pegá el JSON de Cookie-Editor (o header string) y Enter", hide_input=True
        )
    try:
        cookies = parse_cookie_input(raw, platform)
    except ValueError as exc:
        raise UsageError(str(exc)) from None
    if not cookies:
        raise UsageError(
            f"no se encontraron cookies válidas de {platform}",
            hint="revisá que sean del dominio correcto (instagram.com / facebook.com)",
        )
    config = ArgosConfig.load()
    config.set(CONFIG_KEYS[platform], cookies)
    names = ", ".join(cookie["name"] for cookie in cookies)
    console.print(f"[green]ok[/green] {len(cookies)} cookies guardadas ({names})")


@app.command()
@_guard
def cookies(
    platform: str = typer.Argument(..., help="instagram | facebook"),
    json_output: bool = typer.Option(
        False, "--json", help="Imprimir el JSON completo a stdout."
    ),
    out: str = typer.Option(None, "--out", help="Guardar en un archivo (0600)."),
) -> None:
    """Exporta las cookies de la sesión actual (Cookie-Editor) para migrarlas a un VPS."""
    from argos.cookies import export_cookies
    from argos.private_fs import atomic_write_private_text

    target = get_platform(platform)
    config = ArgosConfig.load()
    with BrowserSession(target.name, config, headless=True) as session:
        result = export_cookies(session.context, target.name)

    if not result:
        console.print(
            f"[yellow]no hay cookies de sesión para {target.name}[/yellow] "
            f"(¿corriste `argos login {target.name}`?)"
        )
        raise typer.Exit(code=1)

    if out:
        atomic_write_private_text(out, json.dumps(result, ensure_ascii=False, indent=2) + "\n")
        console.print(f"[green]ok[/green] {len(result)} cookies exportadas a {out} (0600)")
    elif json_output:
        typer.echo(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        for cookie in result:
            value = str(cookie["value"])
            shown = value[:6] + "…" if len(value) > 6 else "…"
            console.print(f"  {cookie['name']} = {shown}")
        console.print("[dim]para el JSON completo usá --json o --out[/dim]")
    err_console.print(
        "[bold yellow]Cuidado:[/bold yellow] estas cookies equivalen a tu contraseña. "
        "No las compartas."
    )


@app.command()
@_guard
def report(
    directory: str = typer.Argument(
        ".",
        help="Carpeta con los JSONL (posts, profiles, comments, search).",
    ),
    title: str = typer.Option(None, "--title", help="Título del informe."),
    json_output: bool = typer.Option(False, "--json", help="Salida JSON con las rutas generadas."),
) -> None:
    """Genera report.md + CSVs + argos.db desde los JSONL de una carpeta."""
    from argos.report import build_report

    result = build_report(Path(directory), title=title)
    if json_output:
        typer.echo(json.dumps(result, ensure_ascii=False, indent=2))
        return
    console.print(f"[green]ok[/green] informe generado en {result['directory']}")
    console.print(f"  {result['markdown']}")
    for csv_path in result["csv"]:
        console.print(f"  {csv_path}")
    console.print(f"  {result['db']}")
    counts = ", ".join(f"{name} {value}" for name, value in result["counts"].items() if value)
    if counts:
        console.print(f"[dim]registros: {counts}[/dim]")


@app.command()
@_guard
def research(
    plan: str = typer.Argument(None, help="YAML con los objetivos (mirá `--example`)."),
    out: str = typer.Option("research", "--out", help="Carpeta base donde crear el job."),
    headed: bool = typer.Option(
        False, "--headed", help="Abrir ventana (ignora `headless` del plan)."
    ),
    example: bool = typer.Option(False, "--example", help="Imprimir un plan de ejemplo y salir."),
    json_output: bool = typer.Option(False, "--json", help="Salida JSON (contrato de agentes)."),
) -> None:
    """Corre varios objetivos (Instagram + Facebook) y arma el informe."""
    from argos.research import EXAMPLE_PLAN, run_research

    if example:
        typer.echo(EXAMPLE_PLAN)
        return
    if not plan:
        raise UsageError(
            "falta el plan YAML",
            hint="pasá un archivo de objetivos o mirá el ejemplo con `argos research --example`",
        )

    result = run_research(Path(plan), base_dir=Path(out), headless=False if headed else None)

    if json_output:
        typer.echo(json.dumps(result, ensure_ascii=False, indent=2))
        return

    ok = sum(1 for item in result["results"] if item.get("status") == "ok")
    console.print(
        f"[green]ok[/green] {ok}/{len(result['results'])} objetivos completados"
    )
    console.print(f"  job: {result['job_dir']}")
    icons = {
        "ok": "[green]✓[/green]",
        "error": "[red]✗[/red]",
        "stopped": "[yellow]![/yellow]",
        "skipped": "[dim]-[/dim]",
    }
    for item in result["results"]:
        icon = icons.get(str(item.get("status")), "?")
        detail = f" · {item['detail']}" if item.get("detail") else ""
        console.print(f"  {icon} {item['target']}{detail}")
    if result["report"]:
        console.print(f"  informe: {result['report']['markdown']}")


# ── Agente autónomo ─────────────────────────────────────────────────

agent_app = typer.Typer(
    help="Agente autónomo: brief → plan LLM → recolección → análisis → informe."
)


def _agent_setup() -> tuple[ArgosConfig, Any]:
    from argos.agent import apply_env_cookies
    from argos.llm import resolve_llm_settings

    config = ArgosConfig.load()
    apply_env_cookies(config)
    settings = resolve_llm_settings(config)
    if settings is None:
        raise UsageError(
            "falta la API del LLM",
            hint=(
                "definí ARGOS_LLM_API_KEY (opcional ARGOS_LLM_BASE_URL / "
                "ARGOS_LLM_MODEL), o configurá llm_api_key en config.yaml"
            ),
        )
    return config, settings


def _agent_out(out: str | None, config: ArgosConfig) -> Path:
    return Path(out) if out else config.home / "runs"


@agent_app.command("plan")
@_guard
def agent_plan(
    brief: str = typer.Option(
        None, "--brief", help="YAML del brief (o ARGOS_BRIEF / ARGOS_BRIEF_FILE)."
    ),
    json_output: bool = typer.Option(False, "--json", help="Salida JSON."),
) -> None:
    """Pide al LLM un plan de objetivos y lo muestra (sin recolectar)."""
    from argos.agent import plan_targets, resolve_brief

    _config, settings = _agent_setup()
    brief_obj = resolve_brief(brief)
    plan = plan_targets(settings, brief_obj)

    if json_output:
        typer.echo(
            json.dumps({"job": brief_obj.name, "targets": plan}, ensure_ascii=False, indent=2)
        )
        return
    console.print(f"[bold]{brief_obj.name}[/bold] — {len(plan)} objetivos")
    for item in plan:
        console.print(
            f"  - {item['type']}: {item.get('value') or '(feed)'} (limit {item['limit']})"
        )


@agent_app.command("run")
@_guard
def agent_run(
    brief: str = typer.Option(
        None, "--brief", help="YAML del brief (o ARGOS_BRIEF / ARGOS_BRIEF_FILE)."
    ),
    out: str = typer.Option(
        None, "--out", help="Carpeta base de las corridas (default <ARGOS_HOME>/runs)."
    ),
    webhook: str = typer.Option(
        None, "--webhook", help="URL para avisar al terminar (o ARGOS_WEBHOOK_URL)."
    ),
    json_output: bool = typer.Option(False, "--json", help="Salida JSON (contrato de agentes)."),
) -> None:
    """Un ciclo completo: plan → recolección → análisis → informe."""
    from argos.agent import resolve_brief, run_once

    config, settings = _agent_setup()
    brief_obj = resolve_brief(brief)
    webhook_url = webhook or os.environ.get("ARGOS_WEBHOOK_URL")
    result = run_once(
        config,
        brief=brief_obj,
        base_dir=_agent_out(out, config),
        settings=settings,
        webhook_url=webhook_url,
    )

    if json_output:
        typer.echo(
            json.dumps(
                {
                    "run_dir": str(result.run_dir),
                    "job_dir": result.job_dir,
                    "analysis": str(result.analysis_path) if result.analysis_path else None,
                    "plan_source": result.plan_source,
                    "plan": result.plan,
                    "results": result.results,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return
    ok = sum(1 for item in result.results if item.get("status") == "ok")
    console.print(f"[green]ok[/green] corrida en {result.run_dir}")
    console.print(f"  plan: {result.plan_source} · {ok}/{len(result.results)} objetivos ok")
    if result.job_dir:
        console.print(f"  datos: {result.job_dir}")
    if result.analysis_path:
        console.print(f"  análisis: {result.analysis_path}")


@agent_app.command("daemon")
@_guard
def agent_daemon(
    brief: str = typer.Option(
        None, "--brief", help="YAML del brief (o ARGOS_BRIEF / ARGOS_BRIEF_FILE)."
    ),
    out: str = typer.Option(None, "--out", help="Carpeta base (default <ARGOS_HOME>/runs)."),
    interval_hours: float = typer.Option(
        None, "--interval-hours", help="Cadencia en horas (default ARGOS_INTERVAL_HOURS o 12)."
    ),
    max_runs: int = typer.Option(
        None, "--max-runs", help="Cortar tras N ciclos (default: sin límite)."
    ),
    webhook: str = typer.Option(None, "--webhook", help="URL para avisar en cada corrida."),
) -> None:
    """Loop de ciclos con cadencia (es lo que corre el contenedor Docker)."""
    from argos.agent import Brief, jobs_dir_for, resolve_brief, run_daemon

    config, settings = _agent_setup()
    interval = interval_hours or float(os.environ.get("ARGOS_INTERVAL_HOURS") or 12)
    base_dir = _agent_out(out, config)
    jobs = jobs_dir_for(config)
    console.print(f"[bold]agente en marcha[/bold] — cada {interval} h · salidas en {base_dir}")
    console.print(
        f"[dim]brief recurrente: {config.home / 'brief.yaml'} (o ARGOS_BRIEF) "
        f"· cola de trabajos: {jobs}[/dim]"
    )

    def _brief_provider() -> Brief:
        return resolve_brief(brief, home=config.home)

    runs = run_daemon(
        config,
        brief_provider=_brief_provider,
        base_dir=base_dir,
        settings=settings,
        interval_hours=interval,
        max_runs=max_runs,
        webhook_url=webhook or os.environ.get("ARGOS_WEBHOOK_URL"),
        jobs_dir=jobs,
    )
    console.print(f"[green]ok[/green] {len(runs)} ciclos completados")


app.add_typer(agent_app, name="agent")


@app.command("ui")
@_guard
def ui(
    host: str = typer.Option(
        "127.0.0.1", "--host", help="Interfaz a escuchar (0.0.0.0 para exponer)."
    ),
    port: int = typer.Option(8756, "--port", help="Puerto HTTP."),
    open_browser: bool = typer.Option(
        True, "--open/--no-open", help="Abrir el navegador al arrancar."
    ),
) -> None:
    """Interfaz web local: brief, LLM, plataformas, corridas y resultados."""
    from argos.web import serve

    serve(host=host, port=port, open_browser=open_browser)


# ── Lugares (OSM gratis / Google Maps scraping) ─────────────────────

places_app = typer.Typer(
    help="Lugares sin costo: OpenStreetMap (gratis) y Google Maps (scraping)."
)


@places_app.command("search")
@_guard
def places_search(
    query: str = typer.Argument(
        ..., help="Qué buscar: 'restaurantes', 'farmacias', o el nombre de un lugar."
    ),
    cerca: str = typer.Option(
        None, "--cerca", help="Zona/ciudad (ej: 'Puebla, MX'). Vacío = búsqueda por nombre."
    ),
    radio: float = typer.Option(5.0, "--radio", help="Radio en km."),
    limite: int = typer.Option(25, "--limite", help="Máximo de lugares."),
    proveedor: str = typer.Option(
        "osm", "--proveedor", help="osm (gratis, default) o gmaps (scraping)."
    ),
    out: str = typer.Option(
        None, "--out", help="Carpeta donde guardar (places.jsonl + reporte + CSV)."
    ),
    json_output: bool = typer.Option(False, "--json", help="Salida JSON."),
) -> None:
    """Busca lugares y, con --out, genera reporte (md + CSV + SQLite)."""
    from argos import places as places_mod
    from argos.report import build_report

    config = ArgosConfig.load()
    result = places_mod.search(
        query,
        location=cerca,
        radius_km=radio,
        limit=limite,
        provider=proveedor,
        config=config,
        headless=True,
    )

    if out:
        out_dir = Path(out)
        out_dir.mkdir(parents=True, exist_ok=True)
        written, _skipped = append_unique_jsonl(
            out_dir / "places.jsonl", result.places, ("source", "id")
        )
        report = build_report(out_dir, title=f"Lugares: {query}")
        console.print(
            f"[green]{written}[/green] lugares en {out_dir} · reporte: {report['markdown']}"
        )

    if json_output:
        typer.echo(
            json.dumps(
                [place.model_dump(mode="json") for place in result.places],
                ensure_ascii=False,
                indent=2,
            )
        )
        return

    table = Table(show_header=True, header_style="bold")
    table.add_column("nombre")
    table.add_column("categoría")
    table.add_column("dirección", overflow="fold")
    table.add_column("tel")
    table.add_column("dist.")
    for place in result.places:
        table.add_row(
            place.name,
            place.category or "",
            (place.address or "")[:60],
            place.phone or "",
            f"{place.distance_km} km" if place.distance_km is not None else "",
        )
    console.print(table)
    console.print(f"[dim]{result.detail}[/dim]")


app.add_typer(places_app, name="places")


# ── Instagram (lectura, DOM-first, con límites) ─────────────────────

ig_app = typer.Typer(
    help="Instagram: leer perfiles y posts (ritmo humano y topes por corrida)."
)


def _print_actions(actions: int, remaining: int) -> None:
    err_console.print(
        f"[dim]acciones de red: {actions} · cuota diaria restante: {remaining}[/dim]"
    )


def _compact_number(value: int | None) -> str:
    """Alias de ``argos.utils.text.compact_number`` (compatibilidad interna)."""
    return compact_number(value)


def _ig_runtime() -> tuple[ArgosConfig, RateLimiter, Pacer]:
    config = ArgosConfig.load()
    return config, RateLimiter(config, "instagram"), Pacer()


def _print_posts_human(posts: list[Post]) -> None:
    for post in posts:
        parts: list[str] = []
        if post.created_at is not None:
            parts.append(post.created_at.date().isoformat())
        if post.likes is not None:
            parts.append(f"{_compact_number(post.likes)} likes")
        if post.comments is not None:
            parts.append(f"{_compact_number(post.comments)} comentarios")
        if post.views is not None:
            parts.append(f"{_compact_number(post.views)} views")
        console.print("[bold]" + (" · ".join(parts) if parts else "—") + "[/bold]")
        caption = (post.caption or "").replace("\n", " ").strip()
        if len(caption) > 140:
            caption = caption[:139] + "…"
        if caption:
            console.print(f"  {caption}")
        console.print(f"  [dim]{post.url}[/dim]")


def _emit_posts(result: PostsResult, *, json_output: bool, out: str | None) -> None:
    if json_output:
        payload = {
            "posts": [post.model_dump(mode="json") for post in result.posts],
            "note": result.note,
            "stopped_at_since": result.stopped_at_since,
        }
        typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        if result.note:
            console.print(f"[yellow]{result.note}[/yellow]")
        _print_posts_human(result.posts)
    if out and result.posts:
        written, skipped = append_unique_jsonl(
            Path(out) / "posts.jsonl", result.posts, ("platform", "id")
        )
        err_console.print(
            f"[dim]posts.jsonl: {written} escritos, {skipped} ya existían[/dim]"
        )
    _print_actions(result.actions, result.daily_remaining)


def _details_option() -> Any:
    return typer.Option(
        False,
        "--details/--no-details",
        help="Visitar cada post/reel para leer métricas y fecha (1 acción por post).",
    )


def _headless_option() -> Any:
    return typer.Option(
        False, "--headless", help="Correr sin ventana (menos parecido a un humano)."
    )


@ig_app.command("profile")
@_guard
def ig_profile(
    username: str = typer.Argument(..., help="Usuario (@handle, nombre o URL del perfil)."),
    limit: int = typer.Option(
        12, "--limit", help=f"Posts de la grilla a listar (máximo {MAX_POSTS_LIMIT})."
    ),
    json_output: bool = typer.Option(False, "--json", help="Salida JSON (contrato de agentes)."),
    out: str = typer.Option(None, "--out", help="Directorio donde guardar profiles.jsonl."),
    headless: bool = typer.Option(
        False, "--headless", help="Correr sin ventana (menos parecido a un humano)."
    ),
) -> None:
    """Lee un perfil público: bio, métricas y los posts visibles en la grilla."""
    config, limiter, pacer = _ig_runtime()
    with BrowserSession("instagram", config, headless=headless) as session:
        result = fetch_profile(
            session, username, limiter=limiter, pacer=pacer, limit=limit
        )

    if json_output:
        payload = {
            "profile": result.profile.model_dump(mode="json"),
            "recent_posts": [post.model_dump(mode="json") for post in result.recent_posts],
            "note": result.note,
        }
        typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        profile = result.profile
        console.print(f"[bold]@{profile.username}[/bold] — {profile.full_name or ''}")
        console.print(
            f"{_compact_number(profile.followers)} seguidores · "
            f"{_compact_number(profile.following)} siguiendo · "
            f"{_compact_number(profile.posts_count)} posts · "
            f"verificada: {bool(profile.is_verified)} · "
            f"privada: {bool(profile.is_private)}"
        )
        if profile.bio:
            console.print(f"bio: {profile.bio}")
        if result.note:
            console.print(f"[yellow]{result.note}[/yellow]")
        for index, post in enumerate(result.recent_posts, 1):
            console.print(f"  {index:>2}. {post.id}  [dim]{post.url}[/dim]")

    if out:
        written, skipped = append_unique_jsonl(
            Path(out) / "profiles.jsonl",
            [result.profile],
            ("platform", "username"),
        )
        err_console.print(
            f"[dim]profiles.jsonl: {written} escritos, {skipped} ya existían[/dim]"
        )
    _print_actions(result.actions, result.daily_remaining)


@ig_app.command("posts")
@_guard
def ig_posts(
    username: str = typer.Argument(..., help="Usuario (@handle, nombre o URL del perfil)."),
    limit: int = typer.Option(
        12, "--limit", help=f"Posts a leer (máximo {MAX_POSTS_LIMIT})."
    ),
    since: str = typer.Option(
        None, "--since", help="Solo posts desde esa fecha ISO (YYYY-MM-DD)."
    ),
    details: bool = typer.Option(
        True,
        "--details/--no-details",
        help="Visitar cada post para leer likes/comentarios/fecha (1 acción por post).",
    ),
    json_output: bool = typer.Option(False, "--json", help="Salida JSON (contrato de agentes)."),
    out: str = typer.Option(None, "--out", help="Directorio donde guardar posts.jsonl."),
    headless: bool = typer.Option(
        False, "--headless", help="Correr sin ventana (menos parecido a un humano)."
    ),
) -> None:
    """Lee los últimos posts de un perfil, con detalle opcional por post."""
    since_value = parse_since(since) if since else None
    config, limiter, pacer = _ig_runtime()
    with BrowserSession("instagram", config, headless=headless) as session:
        result = fetch_posts(
            session,
            username,
            limiter=limiter,
            pacer=pacer,
            limit=limit,
            details=details,
            since=since_value,
        )

    _emit_posts(result, json_output=json_output, out=out)


@ig_app.command("hashtag")
@_guard
def ig_hashtag(
    tag: str = typer.Argument(..., help="Hashtag (#etiqueta o la etiqueta sola)."),
    limit: int = typer.Option(
        12, "--limit", help=f"Posts a listar (máximo {MAX_POSTS_LIMIT})."
    ),
    since: str = typer.Option(
        None, "--since", help="Solo posts desde esa fecha ISO (con --details)."
    ),
    details: bool = _details_option(),
    json_output: bool = typer.Option(False, "--json", help="Salida JSON (contrato de agentes)."),
    out: str = typer.Option(None, "--out", help="Directorio donde guardar posts.jsonl."),
    headless: bool = _headless_option(),
) -> None:
    """Posts de un hashtag (grilla; con --details, métricas por post)."""
    since_value = parse_since(since) if since else None
    config, limiter, pacer = _ig_runtime()
    with BrowserSession("instagram", config, headless=headless) as session:
        result = fetch_hashtag(
            session,
            tag,
            limiter=limiter,
            pacer=pacer,
            limit=limit,
            details=details,
            since=since_value,
        )

    _emit_posts(result, json_output=json_output, out=out)


@ig_app.command("reels")
@_guard
def ig_reels(
    username: str = typer.Argument(..., help="Usuario (@handle, nombre o URL del perfil)."),
    limit: int = typer.Option(
        12, "--limit", help=f"Reels a listar (máximo {MAX_POSTS_LIMIT})."
    ),
    since: str = typer.Option(
        None, "--since", help="Solo reels desde esa fecha ISO (con --details)."
    ),
    details: bool = _details_option(),
    json_output: bool = typer.Option(False, "--json", help="Salida JSON (contrato de agentes)."),
    out: str = typer.Option(None, "--out", help="Directorio donde guardar posts.jsonl."),
    headless: bool = _headless_option(),
) -> None:
    """Reels de un perfil (pestaña /reels/; con --details, métricas por reel)."""
    since_value = parse_since(since) if since else None
    config, limiter, pacer = _ig_runtime()
    with BrowserSession("instagram", config, headless=headless) as session:
        result = fetch_reels(
            session,
            username,
            limiter=limiter,
            pacer=pacer,
            limit=limit,
            details=details,
            since=since_value,
        )

    _emit_posts(result, json_output=json_output, out=out)


@ig_app.command("search")
@_guard
def ig_search(
    query: str = typer.Argument(..., help="Texto a buscar (o #hashtag)."),
    kind: str = typer.Option(
        "posts", "--type", help="posts (grid por keyword) | users (panel de búsqueda)."
    ),
    limit: int = typer.Option(
        12, "--limit", help=f"Resultados a listar (máximo {MAX_POSTS_LIMIT})."
    ),
    variants: bool = typer.Option(
        False,
        "--variants",
        help="Probar variantes del nombre (quitar/invertir apellidos o estilo usuario).",
    ),
    json_output: bool = typer.Option(False, "--json", help="Salida JSON (contrato de agentes)."),
    out: str = typer.Option(None, "--out", help="Directorio donde guardar resultados."),
    headless: bool = _headless_option(),
) -> None:
    """Busca en Instagram: posts por keyword o usuarios (typeahead)."""
    config, limiter, pacer = _ig_runtime()
    with BrowserSession("instagram", config, headless=headless) as session:
        result = search(
            session,
            query,
            limiter=limiter,
            pacer=pacer,
            kind=kind,
            limit=limit,
            variants=variants,
        )

    if json_output:
        payload = {
            "posts": [post.model_dump(mode="json") for post in result.posts],
            "users": [hit.model_dump(mode="json") for hit in result.hits],
            "note": result.note,
        }
        typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        if result.note:
            console.print(f"[yellow]{result.note}[/yellow]")
        for hit in result.hits:
            followers = (
                f" · {_compact_number(hit.followers)} seguidores" if hit.followers else ""
            )
            console.print(f"  @{hit.username} — {hit.name}{followers}")
            console.print(f"    [dim]{hit.url}[/dim]")
        _print_posts_human(result.posts)

    if out:
        if result.hits:
            written, skipped = append_unique_jsonl(
                Path(out) / "search.jsonl", result.hits, ("platform", "url")
            )
            err_console.print(
                f"[dim]search.jsonl: {written} escritos, {skipped} ya existían[/dim]"
            )
        if result.posts:
            written, skipped = append_unique_jsonl(
                Path(out) / "posts.jsonl", result.posts, ("platform", "id")
            )
            err_console.print(
                f"[dim]posts.jsonl: {written} escritos, {skipped} ya existían[/dim]"
            )
    _print_actions(result.actions, result.daily_remaining)


@ig_app.command("comments")
@_guard
def ig_comments(
    post: str = typer.Argument(..., help="URL del post (o shortcode) a leer."),
    limit: int = typer.Option(
        20, "--limit", help=f"Comentarios a leer (máximo {MAX_COMMENTS_LIMIT})."
    ),
    json_output: bool = typer.Option(False, "--json", help="Salida JSON (contrato de agentes)."),
    out: str = typer.Option(None, "--out", help="Directorio donde guardar comments.jsonl."),
    headless: bool = _headless_option(),
) -> None:
    """Comentarios visibles de un post (autor, texto y antigüedad relativa)."""
    config, limiter, pacer = _ig_runtime()
    with BrowserSession("instagram", config, headless=headless) as session:
        result = fetch_comments(session, post, limiter=limiter, pacer=pacer, limit=limit)

    if json_output:
        payload = {
            "comments": [comment.model_dump(mode="json") for comment in result.comments],
            "note": result.note,
        }
        typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        if result.note:
            console.print(f"[yellow]{result.note}[/yellow]")
        for comment in result.comments:
            age = f" · hace {comment.age_text}" if comment.age_text else ""
            console.print(f"[bold]@{comment.author or '—'}[/bold]{age}")
            text = comment.text.replace("\n", " ")
            if len(text) > 200:
                text = text[:199] + "…"
            console.print(f"  {text}")
            console.print(f"  [dim]{comment.url}[/dim]")

    if out and result.comments:
        written, skipped = append_unique_jsonl(
            Path(out) / "comments.jsonl",
            result.comments,
            ("post_url", "id"),
        )
        err_console.print(
            f"[dim]comments.jsonl: {written} escritos, {skipped} ya existían[/dim]"
        )
    _print_actions(result.actions, result.daily_remaining)


app.add_typer(ig_app, name="ig")


# ── Facebook (lectura, DOM-first, con límites) ──────────────────────

fb_app = typer.Typer(
    help="Facebook: leer páginas, buscar y ver los posts de tus grupos."
)


def _fb_runtime() -> tuple[ArgosConfig, RateLimiter, Pacer]:
    config = ArgosConfig.load()
    return config, RateLimiter(config, "facebook"), Pacer()


@fb_app.command("page")
@_guard
def fb_page(
    page: str = typer.Argument(..., help="Slug de la página (NASA) o su URL."),
    limit: int = typer.Option(
        12, "--limit", help=f"Posts a leer (máximo {MAX_POSTS_LIMIT})."
    ),
    json_output: bool = typer.Option(False, "--json", help="Salida JSON (contrato de agentes)."),
    out: str = typer.Option(
        None, "--out", help="Directorio donde guardar profiles.jsonl y posts.jsonl."
    ),
    headless: bool = _headless_option(),
) -> None:
    """Lee una página de Facebook: info del header y posts visibles."""
    config, limiter, pacer = _fb_runtime()
    with BrowserSession("facebook", config, headless=headless) as session:
        result = fetch_page(session, page, limiter=limiter, pacer=pacer, limit=limit)

    if json_output:
        payload = {
            "profile": result.profile.model_dump(mode="json"),
            "posts": [post.model_dump(mode="json") for post in result.posts],
            "note": result.note,
        }
        typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        profile = result.profile
        console.print(f"[bold]@{profile.username}[/bold] — {profile.full_name or ''}")
        console.print(
            f"{_compact_number(profile.followers)} seguidores · "
            f"{_compact_number(profile.following)} seguidos"
        )
        if result.note:
            console.print(f"[yellow]{result.note}[/yellow]")
        _print_posts_human(result.posts)

    if out:
        written, skipped = append_unique_jsonl(
            Path(out) / "profiles.jsonl", [result.profile], ("platform", "username")
        )
        err_console.print(
            f"[dim]profiles.jsonl: {written} escritos, {skipped} ya existían[/dim]"
        )
        if result.posts:
            written, skipped = append_unique_jsonl(
                Path(out) / "posts.jsonl", result.posts, ("platform", "id")
            )
            err_console.print(
                f"[dim]posts.jsonl: {written} escritos, {skipped} ya existían[/dim]"
            )
    _print_actions(result.actions, result.daily_remaining)


@fb_app.command("search")
@_guard
def fb_search_command(
    query: str = typer.Argument(..., help="Texto a buscar."),
    kind: str = typer.Option(
        "pages", "--type", help="pages | groups | people."
    ),
    limit: int = typer.Option(
        12, "--limit", help=f"Resultados a listar (máximo {MAX_POSTS_LIMIT})."
    ),
    variants: bool = typer.Option(
        False, "--variants", help="Probar variantes del nombre (quitar/invertir apellidos)."
    ),
    json_output: bool = typer.Option(False, "--json", help="Salida JSON (contrato de agentes)."),
    out: str = typer.Option(None, "--out", help="Directorio donde guardar search.jsonl."),
    headless: bool = _headless_option(),
) -> None:
    """Busca páginas, grupos o personas en Facebook."""
    config, limiter, pacer = _fb_runtime()
    with BrowserSession("facebook", config, headless=headless) as session:
        result = fb_search(
            session,
            query,
            limiter=limiter,
            pacer=pacer,
            kind=kind,
            limit=limit,
            variants=variants,
        )

    if json_output:
        payload = {
            "results": [hit.model_dump(mode="json") for hit in result.hits],
            "note": result.note,
        }
        typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        for hit in result.hits:
            followers = (
                f" · {_compact_number(hit.followers)} seguidores" if hit.followers else ""
            )
            console.print(f"  {hit.name}{followers}")
            console.print(f"    [dim]{hit.url}[/dim]")

    if out and result.hits:
        written, skipped = append_unique_jsonl(
            Path(out) / "search.jsonl", result.hits, ("platform", "url")
        )
        err_console.print(
            f"[dim]search.jsonl: {written} escritos, {skipped} ya existían[/dim]"
        )
    _print_actions(result.actions, result.daily_remaining)


@fb_app.command("groups-feed")
@_guard
def fb_groups_feed(
    limit: int = typer.Option(12, "--limit", help=f"Posts a leer (máximo {MAX_POSTS_LIMIT})."),
    json_output: bool = typer.Option(False, "--json", help="Salida JSON (contrato de agentes)."),
    out: str = typer.Option(None, "--out", help="Directorio donde guardar posts.jsonl."),
    headless: bool = _headless_option(),
) -> None:
    """Lee el feed de posts de los grupos a los que pertenecés."""
    config, limiter, pacer = _fb_runtime()
    with BrowserSession("facebook", config, headless=headless) as session:
        result = fetch_group_feed(
            session, limiter=limiter, pacer=pacer, limit=limit
        )

    if json_output:
        payload = {
            "posts": [post.model_dump(mode="json") for post in result.posts],
            "note": result.note,
        }
        typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        if result.note:
            console.print(f"[yellow]{result.note}[/yellow]")
        _print_posts_human(result.posts)

    if out and result.posts:
        written, skipped = append_unique_jsonl(
            Path(out) / "posts.jsonl", result.posts, ("platform", "id")
        )
        err_console.print(
            f"[dim]posts.jsonl: {written} escritos, {skipped} ya existían[/dim]"
        )
    _print_actions(result.actions, result.daily_remaining)


app.add_typer(fb_app, name="fb")


def _ensure_utf8_output() -> None:
    """Salidas canalizadas (agentes) deben ser UTF-8, también en Windows."""
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            with contextlib.suppress(OSError, ValueError):
                reconfigure(encoding="utf-8", errors="replace")


def main() -> None:
    _ensure_utf8_output()
    app()


if __name__ == "__main__":
    main()
