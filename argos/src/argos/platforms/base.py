"""Interfaz de plataforma y flujo de login asistido (humano en la ventana)."""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Literal

from playwright.sync_api import Error as PlaywrightError
from rich.console import Console

from argos.browser.checkpoints import Problem
from argos.browser.session import BrowserSession
from argos.config import ArgosConfig
from argos.errors import CheckpointError, LoginRequiredError

Status = Literal["ok", "needs-login", "checkpoint", "rate-limited", "off", "error"]

_console = Console(stderr=True)


@dataclass(frozen=True)
class PlatformStatus:
    """Resultado de un probe o de un login, serializable como contrato."""

    platform: str
    status: Status
    detail: str
    hint: str | None = None
    active_backend: str | None = None

    def as_dict(self) -> dict[str, str | None]:
        return {
            "platform": self.platform,
            "status": self.status,
            "detail": self.detail,
            "hint": self.hint,
            "active_backend": self.active_backend,
        }


class Platform(ABC):
    """Una plataforma = dominio + probe real de sesión (+ flujos, fases 2-4)."""

    name: str = ""
    title: str = ""
    login_url: str = ""
    session_cookies: tuple[str, ...] = ()
    backends: tuple[str, ...] = ()

    @abstractmethod
    def probe(self, session: BrowserSession, *, navigate: bool = True) -> PlatformStatus:
        """Verifica la sesión contra la plataforma y devuelve el estado."""

    def login_hint(self) -> str:
        return (
            f"ejecutá `argos login {self.name}` "
            "e iniciá sesión en la ventana del navegador"
        )

    def _problem_status(self, problem: Problem) -> PlatformStatus:
        if problem.kind == "login":
            return PlatformStatus(
                self.name, "needs-login", problem.detail, hint=self.login_hint()
            )
        if problem.kind == "checkpoint":
            return PlatformStatus(
                self.name,
                "checkpoint",
                problem.detail,
                hint="resolvé la verificación en la ventana del navegador y reintentá",
            )
        return PlatformStatus(
            self.name,
            "rate-limited",
            problem.detail,
            hint="esperá unos minutos antes de reintentar",
        )


def run_login(
    platform: Platform,
    config: ArgosConfig,
    *,
    timeout_s: int = 600,
    proxy: str | None = None,
    poll_interval_s: float = 2.5,
    reprobe_interval_s: float = 15.0,
    reprobe_max_interval_s: float = 120.0,
) -> PlatformStatus:
    """Abre el navegador, espera el login humano y verifica la sesión.

    No pide ni guarda credenciales: el usuario inicia sesión en la ventana.
    Devuelve el estado ``ok`` verificado o lanza ``LoginRequiredError`` /
    ``CheckpointError`` si se agota el tiempo.

    Los re-probes se espacian exponencialmente (15s → 30s → 60s → 120s) para no
    golpear la plataforma mientras el usuario completa el login.
    """
    with BrowserSession(platform.name, config, headless=False, proxy=proxy) as session:
        try:
            session.goto(platform.login_url)
            _console.print(
                f"[bold]Iniciá sesión en {platform.title}[/bold] "
                "dentro de la ventana que se acaba de abrir."
            )
            _console.print(
                "La sesión se detecta sola cuando termines; no hace falta tocar la terminal."
            )

            deadline = time.monotonic() + timeout_s
            last_reprobe = 0.0
            next_reprobe_in = reprobe_interval_s
            probes_done = 0
            last_problem_kind: str | None = None
            last_problem: Problem | None = None
            last_probe_note: str | None = None

            while time.monotonic() < deadline:
                problem = session.inspect()
                if problem is not None and problem.kind != last_problem_kind:
                    if problem.kind == "checkpoint":
                        _console.print(
                            f"[yellow]Verificación pendiente:[/yellow] {problem.detail}"
                        )
                    last_problem_kind = problem.kind
                    last_problem = problem

                cookies = session.cookies()
                if all(name in cookies for name in platform.session_cookies):
                    now = time.monotonic()
                    if now - last_reprobe >= next_reprobe_in:
                        last_reprobe = now
                        probes_done += 1
                        # Espaciado exponencial: no golpear la plataforma.
                        next_reprobe_in = min(
                            reprobe_max_interval_s,
                            reprobe_interval_s * (2**probes_done),
                        )
                        status = platform.probe(session, navigate=False)
                        if status.status == "ok":
                            return status
                        if status.status == "needs-login":
                            last_problem = Problem("login", status.detail)
                        else:
                            # Visibilidad para estados no concluyentes (rate limit,
                            # errores de API): sin esto el login espera en silencio.
                            note = f"{status.status}: {status.detail}"
                            if note != last_probe_note:
                                _console.print(f"[dim]verificación de sesión → {note}[/dim]")
                                last_probe_note = note
                time.sleep(poll_interval_s)

            if last_problem is not None and last_problem.kind == "checkpoint":
                raise CheckpointError(
                    f"{platform.name}: verificación pendiente al agotarse el tiempo "
                    f"({last_problem.detail})",
                    hint="resolvé la verificación en el navegador y repetí `argos login`",
                )
            raise LoginRequiredError(
                f"{platform.name}: no se detectó una sesión válida en {timeout_s} s",
                hint=(
                    f"reintentá `argos login {platform.name}` "
                    "y completá el login en la ventana"
                ),
            )
        except PlaywrightError as exc:
            # El usuario cerró la ventana (o el navegador murió) durante el login.
            raise LoginRequiredError(
                f"{platform.name}: la ventana del navegador se cerró "
                "antes de detectar la sesión",
                hint=(
                    f"volvé a ejecutar `argos login {platform.name}` y no cierres "
                    "la ventana hasta que la sesión quede confirmada"
                ),
            ) from exc
