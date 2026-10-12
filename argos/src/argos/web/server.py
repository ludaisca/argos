"""Interfaz web local de Argos: FastAPI + assets estáticos.

Pensada para correr en tu máquina (``argos ui``) y, más adelante, dentro del
contenedor. Todo lo que hace pasa por los mismos módulos del CLI (config,
agente, research, quota, doctor): la UI no tiene lógica propia de recolección.

Sin autenticación salvo que definas ``ARGOS_UI_TOKEN`` (header ``Authorization:
Bearer …`` o ``?token=…``).
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import subprocess
import sys
import threading
import time
import uuid
import webbrowser
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import yaml
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from argos.agent import (
    MAX_TARGETS,
    Brief,
    jobs_dir_for,
    load_brief,
    plan_targets,
)
from argos.config import ArgosConfig
from argos.cookies import CONFIG_KEYS
from argos.doctor import collect as doctor_collect
from argos.errors import ArgosError, UsageError
from argos.llm import (
    DEFAULT_BASE_URL,
    DEFAULT_MODEL,
    LLMError,
    chat,
    resolve_llm_settings,
)
from argos.private_fs import atomic_write_private_text
from argos.quota import quota_report
from argos.research import TARGET_PLATFORM

STATIC_DIR = Path(__file__).parent / "static"
_TARGET_LIMIT_CAP = 20
_SLUG_RE = re.compile(r"[\w.\-]+")


# --------------------------------------------------------------------------- #
# Modelos de entrada
# --------------------------------------------------------------------------- #


class BriefPayload(BaseModel):
    job: str = "research"
    objective: str = ""
    questions: list[str] = []
    platforms: list[str] = []
    targets: list[dict[str, Any]] = []
    max_targets: int = MAX_TARGETS


class SettingsPayload(BaseModel):
    llm_api_key: str | None = None
    llm_base_url: str | None = None
    llm_model: str | None = None
    interval_hours: float | None = None


class RunPayload(BaseModel):
    source: Literal["brief", "job"] = "brief"
    job: str | None = None


class DaemonPayload(BaseModel):
    interval_hours: float | None = None


class JobPayload(BriefPayload):
    filename: str | None = None
    overwrite: bool = False


# --------------------------------------------------------------------------- #
# Registro de procesos
# --------------------------------------------------------------------------- #


@dataclass
class ProcRecord:
    id: str
    kind: str  # "run" | "daemon"
    label: str
    status: str = "running"  # running | ok | error | stopped
    started_at: str = field(
        default_factory=lambda: dt.datetime.now(dt.UTC).isoformat(timespec="seconds")
    )
    finished_at: str | None = None
    exit_code: int | None = None
    log: str = ""
    result: dict[str, Any] | None = None
    proc: subprocess.Popen[bytes] | None = field(default=None, repr=False)

    def as_dict(self, log_tail: int = 30000) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "label": self.label,
            "status": self.status,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "exit_code": self.exit_code,
            "result": self.result,
            "log": self.log[-log_tail:],
        }


# --------------------------------------------------------------------------- #
# Servicio
# --------------------------------------------------------------------------- #


class UIService:
    def __init__(self, home: Path | None = None) -> None:
        self.config = ArgosConfig.load(home)
        self.home = self.config.home
        self.records: dict[str, ProcRecord] = {}
        self.daemon_record: ProcRecord | None = None
        self.daemon_proc: subprocess.Popen[bytes] | None = None

    # ----- brief ----- #

    def current_brief(self) -> tuple[Brief | None, str]:
        """(brief, fuente) tolerante: ``none`` si no hay nada configurado."""
        env_file = os.environ.get("ARGOS_BRIEF_FILE")
        if env_file and Path(env_file).is_file():
            return load_brief(path=Path(env_file)), "env-file"
        volume = self.home / "brief.yaml"
        if volume.is_file():
            return load_brief(path=volume), "home"
        env_text = os.environ.get("ARGOS_BRIEF")
        if env_text:
            return load_brief(text=env_text), "env"
        return None, "none"

    def current_brief_required(self) -> tuple[Brief, str]:
        try:
            brief, source = self.current_brief()
        except ArgosError as exc:
            raise HTTPException(422, str(exc)) from exc
        if brief is None:
            raise HTTPException(
                422, "no hay brief: guardá uno en la pestaña Investigación"
            )
        return brief, source

    def brief_payload(self, brief: Brief, source: str) -> dict[str, Any]:
        return {
            "source": source,
            "job": brief.name,
            "objective": brief.objective,
            "questions": brief.questions,
            "targets": brief.targets,
            "max_targets": brief.max_targets,
            "platforms": brief.platforms,
        }

    def brief_info(self) -> dict[str, Any]:
        brief, source = self.current_brief()
        if brief is None:
            return {"source": "none"}
        return self.brief_payload(brief, source)

    # ----- settings ----- #

    @staticmethod
    def _mask(value: str | None) -> str | None:
        if not value:
            return None
        if len(value) <= 8:
            return "…"
        return f"{value[:4]}…{value[-4:]}"

    def settings_payload(self) -> dict[str, Any]:
        settings = resolve_llm_settings(self.config)
        env_key = os.environ.get("ARGOS_LLM_API_KEY")
        config_key = self.config.get("llm_api_key")
        raw_key = env_key or config_key
        return {
            "llm_configured": settings is not None,
            "llm_key_set": bool(raw_key),
            "llm_key_masked": self._mask(str(raw_key) if raw_key else None),
            "llm_key_source": "env" if env_key else ("config" if config_key else None),
            "llm_base_url": settings.base_url
            if settings
            else str(
                os.environ.get("ARGOS_LLM_BASE_URL")
                or self.config.get("llm_base_url")
                or DEFAULT_BASE_URL
            ),
            "llm_model": settings.model
            if settings
            else str(
                os.environ.get("ARGOS_LLM_MODEL")
                or self.config.get("llm_model")
                or DEFAULT_MODEL
            ),
            "interval_hours": float(
                self.config.get("interval_hours")
                or os.environ.get("ARGOS_INTERVAL_HOURS")
                or 12
            ),
        }

    # ----- estado ----- #

    def status(self) -> dict[str, Any]:
        sessions: dict[str, Any] = {}
        for platform, key in CONFIG_KEYS.items():
            cookies = self.config.get(key) or []
            profile = self.config.profile_dir(platform)
            sessions[platform] = {
                "cookies": len(cookies) if isinstance(cookies, list) else 0,
                "profile": profile.is_dir() and any(profile.iterdir()),
            }
        jobs = self.list_jobs()
        return {
            "home": str(self.home),
            "llm": {
                key: value
                for key, value in self.settings_payload().items()
                if key.startswith("llm_")
            },
            "interval_hours": self.settings_payload()["interval_hours"],
            "sessions": sessions,
            "quota": quota_report(self.config),
            "jobs": {
                "pending": len(jobs["pending"]),
                "done": len(jobs["done"]),
                "failed": len(jobs["failed"]),
            },
            "runs": self.list_runs()[:5],
            "brief": self.brief_info(),
            "daemon": self.daemon_state()["running"],
            "busy": self.run_busy(),
        }

    # ----- corridas (archivos) ----- #

    def runs_dir(self) -> Path:
        return self.home / "runs"

    def _safe_dir(self, base: Path, name: str) -> Path:
        if not _SLUG_RE.fullmatch(name):
            raise HTTPException(400, "nombre inválido")
        target = (base / name).resolve()
        if target.parent != base.resolve() or not target.is_dir():
            raise HTTPException(404, "no encontrado")
        return target

    def _read_json(self, path: Path) -> dict[str, Any]:
        if not path.is_file():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def list_runs(self) -> list[dict[str, Any]]:
        base = self.runs_dir()
        items: list[dict[str, Any]] = []
        if not base.is_dir():
            return items
        for entry in sorted(base.iterdir(), reverse=True):
            if not entry.is_dir():
                continue
            meta = self._read_json(entry / "run.json")
            results = list(meta.get("results") or [])
            items.append(
                {
                    "name": entry.name,
                    "job": str(meta.get("job") or entry.name),
                    "objective": str(meta.get("objective") or ""),
                    "plan_source": meta.get("plan_source"),
                    "platforms": meta.get("platforms"),
                    "generated_at": meta.get("generated_at"),
                    "ok": sum(1 for item in results if item.get("status") == "ok"),
                    "total": len(results),
                    "analysis": (entry / "analysis.md").is_file(),
                }
            )
        return items

    def run_detail(self, name: str) -> dict[str, Any]:
        run_dir = self._safe_dir(self.runs_dir(), name)
        meta = self._read_json(run_dir / "run.json")
        analysis: str | None = None
        analysis_path = run_dir / "analysis.md"
        if analysis_path.is_file():
            analysis = analysis_path.read_text(encoding="utf-8", errors="replace")
        files = [
            {
                "path": path.relative_to(run_dir).as_posix(),
                "size": path.stat().st_size,
            }
            for path in sorted(run_dir.rglob("*"))
            if path.is_file()
        ]
        return {"name": name, "meta": meta, "analysis": analysis, "files": files}

    def run_file(self, name: str, rel: str) -> Path:
        run_dir = self._safe_dir(self.runs_dir(), name)
        target = (run_dir / rel).resolve()
        if not target.is_relative_to(run_dir) or not target.is_file():
            raise HTTPException(404, "archivo no encontrado")
        return target

    # ----- jobs (cola) ----- #

    def jobs_dir(self) -> Path:
        return jobs_dir_for(self.config)

    def job_file(self, name: str) -> Path:
        if not re.fullmatch(r"[\w.\-]+\.ya?ml", name):
            raise HTTPException(400, "nombre de trabajo inválido")
        base = self.jobs_dir().resolve()
        target = (base / name).resolve()
        if target.parent != base or not target.is_file():
            raise HTTPException(404, "trabajo no encontrado")
        return target

    def list_jobs(self) -> dict[str, Any]:
        base = self.jobs_dir()
        result: dict[str, Any] = {"dir": str(base), "pending": [], "done": [], "failed": []}
        if not base.is_dir():
            return result
        for bucket in ("done", "failed"):
            folder = base / bucket
            if folder.is_dir():
                result[bucket] = sorted(
                    path.name
                    for path in folder.iterdir()
                    if path.is_file() and path.suffix in (".yaml", ".yml")
                )
        for path in sorted(list(base.glob("*.yaml")) + list(base.glob("*.yml"))):
            entry: dict[str, Any] = {"file": path.name}
            try:
                brief = load_brief(path=path)
                entry.update(
                    {
                        "job": brief.name,
                        "objective": brief.objective,
                        "platforms": brief.platforms,
                    }
                )
            except ArgosError as exc:
                entry["error"] = str(exc)
            result["pending"].append(entry)
        return result

    # ----- procesos ----- #

    def run_busy(self) -> bool:
        return any(
            record.kind == "run" and record.status == "running"
            for record in self.records.values()
        )

    def _pump(self, stream: Any, record: ProcRecord, *, to_log: bool) -> str:
        collected: list[str] = []
        for raw in iter(stream.readline, b""):
            text = raw.decode("utf-8", "replace")
            collected.append(text)
            if to_log:
                record.log = (record.log + text)[-200_000:]
        return "".join(collected)

    @staticmethod
    def _parse_json(raw: str) -> dict[str, Any] | None:
        start, end = raw.find("{"), raw.rfind("}")
        if start < 0 or end <= start:
            return None
        try:
            data = json.loads(raw[start : end + 1])
        except ValueError:
            return None
        return data if isinstance(data, dict) else None

    def launch(self, args: list[str], *, kind: str, label: str) -> ProcRecord:
        record = ProcRecord(id=uuid.uuid4().hex[:12], kind=kind, label=label)
        self.records[record.id] = record
        env = os.environ.copy()
        env.setdefault("ARGOS_HOME", str(self.home))
        env["PYTHONIOENCODING"] = "utf-8"
        cmd = [sys.executable, "-m", "argos.cli", *args]
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
                cwd=str(self.home),
            )
        except OSError as exc:
            record.status = "error"
            record.log = f"no se pudo lanzar: {exc}\n"
            record.finished_at = dt.datetime.now(dt.UTC).isoformat(timespec="seconds")
            return record
        record.proc = proc
        threading.Thread(
            target=self._watch, args=(proc, record), daemon=True
        ).start()
        return record

    def _watch(self, proc: subprocess.Popen[bytes], record: ProcRecord) -> None:
        holder: dict[str, str] = {}

        def _stdout() -> None:
            if proc.stdout is not None:
                holder["out"] = self._pump(proc.stdout, record, to_log=False)

        thread = threading.Thread(target=_stdout, daemon=True)
        thread.start()
        if proc.stderr is not None:
            self._pump(proc.stderr, record, to_log=True)
        thread.join(timeout=10)
        proc.wait()
        record.exit_code = proc.returncode
        record.finished_at = dt.datetime.now(dt.UTC).isoformat(timespec="seconds")
        if record.status == "running":
            record.status = "ok" if proc.returncode == 0 else "error"
        if record.kind == "run":
            data = self._parse_json(holder.get("out", ""))
            if data:
                run_dir = data.get("run_dir")
                if isinstance(run_dir, str):
                    data["run_name"] = Path(run_dir).name
                record.result = data
        if record is self.daemon_record and record.status != "stopped":
            self.daemon_proc = None

    def cancel(self, record_id: str) -> ProcRecord:
        record = self.records.get(record_id)
        if record is None:
            raise HTTPException(404, "corrida no encontrada")
        if record.proc is not None and record.proc.poll() is None:
            record.status = "stopped"
            record.proc.terminate()
        return record

    # ----- daemon ----- #

    def daemon_start(self, interval_hours: float) -> ProcRecord:
        if self.daemon_proc is not None and self.daemon_proc.poll() is None:
            raise HTTPException(409, "el daemon ya está corriendo")
        record = self.launch(
            ["agent", "daemon", "--interval-hours", str(interval_hours)],
            kind="daemon",
            label=f"daemon cada {interval_hours} h",
        )
        self.daemon_record = record
        self.daemon_proc = record.proc
        return record

    def daemon_stop(self) -> dict[str, Any]:
        record = self.daemon_record
        if record is None or self.daemon_proc is None or self.daemon_proc.poll() is not None:
            self.daemon_proc = None
            return {"running": False}
        record.status = "stopped"
        self.daemon_proc.terminate()
        self.daemon_proc = None
        return {"running": False, "id": record.id}

    def daemon_state(self) -> dict[str, Any]:
        running = self.daemon_proc is not None and self.daemon_proc.poll() is None
        return {
            "running": running,
            "record": self.daemon_record.as_dict(log_tail=6000)
            if self.daemon_record
            else None,
        }


# --------------------------------------------------------------------------- #
# App
# --------------------------------------------------------------------------- #


def _meta_payload(service: UIService) -> dict[str, Any]:
    platforms = sorted(set(TARGET_PLATFORM.values()))
    return {
        "home": str(service.home),
        "jobs_dir": str(service.jobs_dir()),
        "runs_dir": str(service.runs_dir()),
        "platforms": platforms,
        "target_types": {
            platform: sorted(
                ttype for ttype, mapped in TARGET_PLATFORM.items() if mapped == platform
            )
            for platform in platforms
        },
        "kinds": {
            "ig_search": ["posts", "users"],
            "fb_search": ["pages", "groups", "people"],
        },
        "max_targets_cap": 12,
        "target_limit_cap": _TARGET_LIMIT_CAP,
    }


def create_app(home: Path | None = None) -> FastAPI:
    service = UIService(home)
    app = FastAPI(title="Argos", docs_url=None, redoc_url=None)
    app.state.service = service
    token = os.environ.get("ARGOS_UI_TOKEN")

    @app.middleware("http")
    async def _auth(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if token:
            header = request.headers.get("authorization", "")
            given = header.removeprefix("Bearer ").strip() or request.query_params.get(
                "token", ""
            )
            if given != token:
                return JSONResponse({"detail": "no autorizado"}, status_code=401)
        return await call_next(request)

    # ----- páginas ----- #

    @app.get("/", response_class=HTMLResponse)
    def index() -> HTMLResponse:
        return HTMLResponse((STATIC_DIR / "index.html").read_text(encoding="utf-8"))

    @app.get("/api/meta")
    def meta() -> dict[str, Any]:
        return _meta_payload(service)

    # ----- estado ----- #

    @app.get("/api/status")
    def status() -> dict[str, Any]:
        return service.status()

    # ----- brief ----- #

    @app.get("/api/brief")
    def get_brief() -> dict[str, Any]:
        try:
            return service.brief_info()
        except ArgosError as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.put("/api/brief")
    def put_brief(payload: BriefPayload) -> dict[str, Any]:
        if not payload.objective.strip():
            raise HTTPException(422, "el objetivo no puede estar vacío")
        data: dict[str, Any] = {
            "job": payload.job.strip() or "research",
            "objective": payload.objective.strip(),
            "platforms": payload.platforms,
            "max_targets": max(1, min(int(payload.max_targets), 12)),
        }
        questions = [item.strip() for item in payload.questions if item.strip()]
        if questions:
            data["questions"] = questions
        if payload.targets:
            data["targets"] = payload.targets
        service.home.mkdir(parents=True, exist_ok=True)
        staging = service.home / "brief.yaml.staging"
        atomic_write_private_text(
            staging, yaml.safe_dump(data, allow_unicode=True, sort_keys=False)
        )
        try:
            brief = load_brief(path=staging)
        except ArgosError as exc:
            staging.unlink(missing_ok=True)
            raise HTTPException(422, str(exc)) from exc
        staging.replace(service.home / "brief.yaml")
        return service.brief_payload(brief, "home")

    # ----- settings ----- #

    @app.get("/api/settings")
    def get_settings() -> dict[str, Any]:
        return service.settings_payload()

    @app.put("/api/settings")
    def put_settings(payload: SettingsPayload) -> dict[str, Any]:
        changed: dict[str, Any] = {}
        if payload.llm_api_key and payload.llm_api_key.strip():
            changed["llm_api_key"] = payload.llm_api_key.strip()
        if payload.llm_base_url and payload.llm_base_url.strip():
            changed["llm_base_url"] = payload.llm_base_url.strip()
        if payload.llm_model and payload.llm_model.strip():
            changed["llm_model"] = payload.llm_model.strip()
        if payload.interval_hours is not None:
            if payload.interval_hours <= 0:
                raise HTTPException(422, "interval_hours debe ser mayor a 0")
            changed["interval_hours"] = float(payload.interval_hours)
        for key, value in changed.items():
            service.config.extra[key] = value
        if changed:
            service.config.save()
        return service.settings_payload()

    @app.post("/api/settings/test-llm")
    def test_llm() -> dict[str, Any]:
        settings = resolve_llm_settings(service.config)
        if settings is None:
            raise HTTPException(400, "falta la API key del LLM")
        try:
            reply = chat(
                settings,
                [{"role": "user", "content": "Responde solo con: ok"}],
                timeout=45,
            )
        except LLMError as exc:
            return {"ok": False, "model": settings.model, "error": str(exc)}
        return {"ok": True, "model": settings.model, "reply": reply.strip()[:200]}

    # ----- planificación ----- #

    @app.post("/api/plan")
    def plan_now() -> dict[str, Any]:
        brief, _source = service.current_brief_required()
        settings = resolve_llm_settings(service.config)
        if settings is None:
            raise HTTPException(400, "falta la API key del LLM")
        try:
            targets = plan_targets(settings, brief)
        except (LLMError, UsageError) as exc:
            raise HTTPException(502, f"el plan falló: {exc}") from exc
        return {"job": brief.name, "platforms": brief.platforms, "targets": targets}

    # ----- corridas ----- #

    @app.post("/api/run")
    def start_run(payload: RunPayload) -> dict[str, Any]:
        if service.run_busy():
            raise HTTPException(409, "ya hay una corrida en curso")
        if payload.source == "job":
            if not payload.job:
                raise HTTPException(422, "falta el nombre del trabajo")
            job_path = service.job_file(payload.job)
            args = ["agent", "run", "--brief", str(job_path), "--json"]
            label = f"job {payload.job}"
        else:
            brief, _source = service.current_brief_required()
            args = ["agent", "run", "--json"]
            label = f"brief {brief.name}"
        return service.launch(args, kind="run", label=label).as_dict()

    @app.get("/api/run/{record_id}")
    def run_state(record_id: str) -> dict[str, Any]:
        record = service.records.get(record_id)
        if record is None:
            raise HTTPException(404, "corrida no encontrada")
        return record.as_dict()

    @app.delete("/api/run/{record_id}")
    def cancel_run(record_id: str) -> dict[str, Any]:
        return service.cancel(record_id).as_dict()

    @app.get("/api/runs")
    def list_runs() -> dict[str, Any]:
        return {"runs": service.list_runs()}

    @app.get("/api/runs/{name}")
    def run_detail(name: str) -> dict[str, Any]:
        return service.run_detail(name)

    @app.get("/api/runs/{name}/file/{rel:path}")
    def run_file(name: str, rel: str) -> FileResponse:
        return FileResponse(service.run_file(name, rel))

    # ----- jobs ----- #

    @app.get("/api/jobs")
    def list_jobs() -> dict[str, Any]:
        return service.list_jobs()

    @app.post("/api/jobs")
    def create_job(payload: JobPayload) -> dict[str, Any]:
        if not payload.objective.strip():
            raise HTTPException(422, "el objetivo no puede estar vacío")
        raw_name = payload.filename or payload.job or "job"
        slug = re.sub(r"[^A-Za-z0-9._-]+", "-", raw_name).strip("-")[:60] or "job"
        filename = slug if slug.endswith((".yaml", ".yml")) else f"{slug}.yaml"
        base = service.jobs_dir()
        base.mkdir(parents=True, exist_ok=True)
        target = base / filename
        if target.exists() and not payload.overwrite:
            raise HTTPException(409, f"{filename} ya existe (usá overwrite para pisarlo)")
        data: dict[str, Any] = {
            "job": payload.job.strip() or slug,
            "objective": payload.objective.strip(),
            "platforms": payload.platforms,
            "max_targets": max(1, min(int(payload.max_targets), 12)),
        }
        questions = [item.strip() for item in payload.questions if item.strip()]
        if questions:
            data["questions"] = questions
        if payload.targets:
            data["targets"] = payload.targets
        staging = base / f"{filename}.staging"
        atomic_write_private_text(
            staging, yaml.safe_dump(data, allow_unicode=True, sort_keys=False)
        )
        try:
            load_brief(path=staging)
        except ArgosError as exc:
            staging.unlink(missing_ok=True)
            raise HTTPException(422, str(exc)) from exc
        staging.replace(target)
        return {"file": filename, "ok": True}

    @app.delete("/api/jobs/{name}")
    def delete_job(name: str) -> dict[str, Any]:
        path = service.job_file(name)
        path.unlink()
        return {"deleted": name}

    # ----- daemon ----- #

    @app.get("/api/daemon")
    def daemon_state() -> dict[str, Any]:
        return service.daemon_state()

    @app.post("/api/daemon")
    def daemon_start(payload: DaemonPayload) -> dict[str, Any]:
        interval = payload.interval_hours or service.settings_payload()["interval_hours"]
        return service.daemon_start(float(interval)).as_dict()

    @app.delete("/api/daemon")
    def daemon_stop() -> dict[str, Any]:
        return service.daemon_stop()

    # ----- doctor ----- #

    @app.post("/api/doctor")
    def doctor() -> dict[str, Any]:
        try:
            return doctor_collect(service.config, headless=True)
        except Exception as exc:  # noqa: BLE001 - doctor no debe tumbar la UI
            raise HTTPException(500, f"doctor falló: {exc}") from exc

    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
    return app


# --------------------------------------------------------------------------- #
# Arranque
# --------------------------------------------------------------------------- #


def serve(host: str = "127.0.0.1", port: int = 8756, open_browser: bool = True) -> None:
    """Levanta la UI con uvicorn (bloqueante)."""
    import uvicorn
    from rich.console import Console

    console = Console(stderr=True)
    app = create_app()
    shown = "127.0.0.1" if host in ("0.0.0.0", "::") else host
    url = f"http://{shown}:{port}"
    console.print(f"[bold]Argos UI[/bold] → {url}")
    if os.environ.get("ARGOS_UI_TOKEN"):
        console.print("[dim]protegida con ARGOS_UI_TOKEN[/dim]")
    if open_browser:

        def _open() -> None:
            time.sleep(0.8)
            webbrowser.open(url)

        threading.Thread(target=_open, daemon=True).start()
    uvicorn.run(app, host=host, port=port, log_level="warning")
