"""Sectores de enriquecimiento (Personalizada)."""

from __future__ import annotations

from argos.sectors.medico import (
    MEDICAL_TIPOS,
    NO_RAMO,
    TIPOS_CLIENTE,
    MedicalVerdict,
    classify,
    detect_specialties,
    suggest_tipo,
)

__all__ = [
    "MEDICAL_TIPOS",
    "NO_RAMO",
    "TIPOS_CLIENTE",
    "MedicalVerdict",
    "classify",
    "detect_specialties",
    "suggest_tipo",
]
