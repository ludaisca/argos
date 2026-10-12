"""Interfaz web local de Argos (FastAPI + estáticos)."""

from __future__ import annotations

from argos.web.server import create_app, serve

__all__ = ["create_app", "serve"]
