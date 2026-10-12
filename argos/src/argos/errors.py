"""Errores tipados con exit codes estables (contrato para agentes)."""

from __future__ import annotations

EXIT_OK = 0
EXIT_INTERNAL = 1
EXIT_USAGE = 2
EXIT_NEEDS_HUMAN = 3
EXIT_RATE_LIMITED = 4
EXIT_EXTRACTION = 5


class ArgosError(Exception):
    """Error esperado: se muestra sin traceback y define el exit code."""

    exit_code: int = EXIT_INTERNAL

    def __init__(self, message: str, *, hint: str | None = None) -> None:
        super().__init__(message)
        self.hint = hint


class UsageError(ArgosError):
    """Entrada inválida del usuario (plataforma desconocida, argumentos mal formados)."""

    exit_code = EXIT_USAGE


class ConfigError(UsageError):
    """La configuración existe pero no es válida."""


class NeedsHumanError(ArgosError):
    """Requiere intervención humana (login o verificación)."""

    exit_code = EXIT_NEEDS_HUMAN


class LoginRequiredError(NeedsHumanError):
    """No hay sesión válida para la plataforma."""


class CheckpointError(NeedsHumanError):
    """La plataforma pide una verificación (captcha/challenge/suspensión)."""

    def __init__(
        self,
        message: str,
        *,
        hint: str | None = None,
        evidence: str | None = None,
    ) -> None:
        super().__init__(message, hint=hint)
        self.evidence = evidence


class RateLimitedError(ArgosError):
    """La plataforma o la cuota local impiden seguir ahora."""

    exit_code = EXIT_RATE_LIMITED

    def __init__(
        self,
        message: str,
        *,
        hint: str | None = None,
        evidence: str | None = None,
    ) -> None:
        super().__init__(message, hint=hint)
        self.evidence = evidence


class ExtractionError(ArgosError):
    """No se pudo extraer/normalizar el contenido esperado."""

    exit_code = EXIT_EXTRACTION
