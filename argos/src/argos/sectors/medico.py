"""Sector médico: señales, especialidades y mapeo al enum de "Tipo de cliente".

El enum es el del CRM del operador; ``classify`` decide si un lead pertenece al
ramo médico y propone tipo/especialidad solo cuando hay señales claras.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

#: Valores exactos permitidos por el CRM (campo "Tipo de cliente").
TIPOS_CLIENTE: tuple[str, ...] = (
    "Ambulancias",
    "AUXILIAR DE RECURSOS HUMANOS",
    "Biomedico",
    "CAPACITADOR",
    "Centro de salud",
    "cliente final",
    "Cliente final",
    "Clinica",
    "Clinica veterinaria",
    "Constructora",
    "Consultorio",
    "Dental",
    "Director",
    "DIRECTOR DE RECURSOS HUMANOS",
    "Distribuidor",
    "Doctor",
    "Empresa",
    "enfermería",
    "Escuelas",
    "Especialidades",
    "EVALUACION Y DESEMPEÑO",
    "GERENTE DE RECURSOS HUMANOS",
    "Hospital",
    "IMSS BIENESTAR",
    "Industria Minera",
    "Jefe de formacion",
    "Laboratorio",
    "licitación",
    "No es del ramo",
    "NOMINAS",
    "Propietario",
    "RECLUTADOR",
    "RELACIONES LABORALES",
    "Rescate",
    "Sanatorio",
    "SELECCIONADOR",
    "Sistema",
    "Traslado",
)

#: Subconjunto del enum que consideramos "ramo médico".
MEDICAL_TIPOS: frozenset[str] = frozenset(
    {
        "Ambulancias",
        "Biomedico",
        "Centro de salud",
        "Clinica",
        "Clinica veterinaria",
        "Consultorio",
        "Dental",
        "Doctor",
        "enfermería",
        "Especialidades",
        "Hospital",
        "IMSS BIENESTAR",
        "Laboratorio",
        "Rescate",
        "Sanatorio",
        "Traslado",
    }
)

NO_RAMO = "No es del ramo"

#: (patrón, tipo sugerido) — el orden importa (lo más específico primero).
_TIPO_RULES: tuple[tuple[tuple[str, ...], str], ...] = (
    (("imss", "bienestar"), "IMSS BIENESTAR"),
    (("veterinar",), "Clinica veterinaria"),
    (("ambulanc",), "Ambulancias"),
    (("traslado",), "Traslado"),
    (("rescate",), "Rescate"),
    (("dental", "odontolog", "ortodoncia", "endodoncia"), "Dental"),
    (("laborator", "analisis clínicos", "analisis clinicos"), "Laboratorio"),
    (("hospital",), "Hospital"),
    (("sanatorio",), "Sanatorio"),
    (
        ("centro de salud", "centro medico", "centro médico", "centro de atencion"),
        "Centro de salud",
    ),
    (("consultorio",), "Consultorio"),
    (("biomedic", "biomédic"), "Biomedico"),
    (("enfermer",), "enfermería"),
    (("clínic", "clinic"), "Clinica"),
    (("dr.", "dra.", "doctor", "médic", "medic", "especialista"), "Doctor"),
)

#: Especialidades comunes (substring normalizado → nombre canónico).
_SPECIALTIES: tuple[tuple[str, str], ...] = (
    ("pediatr", "Pediatría"),
    ("cardiolog", "Cardiología"),
    ("dermatolog", "Dermatología"),
    ("ginecolog", "Ginecología"),
    ("obstetric", "Obstetricia"),
    ("oftalmolog", "Oftalmología"),
    ("traumatolog", "Traumatología"),
    ("ortoped", "Ortopedia"),
    ("odontolog", "Odontología"),
    ("ortodoncia", "Ortodoncia"),
    ("endodoncia", "Endodoncia"),
    ("psiquiatr", "Psiquiatría"),
    ("neurolog", "Neurología"),
    ("oncolog", "Oncología"),
    ("urolog", "Urología"),
    ("nefrolog", "Nefrología"),
    ("gastroenterolog", "Gastroenterología"),
    ("neumolog", "Neumología"),
    ("endocrinolog", "Endocrinología"),
    ("reumatolog", "Reumatología"),
    ("anestesiolog", "Anestesiología"),
    ("radiolog", "Radiología"),
    ("otorrinolaringolog", "Otorrinolaringología"),
    ("hematolog", "Hematología"),
    ("infectolog", "Infectología"),
    ("fisioterap", "Fisioterapia"),
    ("nutriolog", "Nutriología"),
    ("nutricion", "Nutrición"),
    ("psicolog", "Psicología"),
    ("geriatri", "Geriatría"),
    ("alergolog", "Alergología"),
    ("cirugia", "Cirugía"),
    ("cirugía", "Cirugía"),
    ("medicina general", "Medicina General"),
    ("medicina familiar", "Medicina Familiar"),
)

#: Señales fuertes de ramo médico (peso 2) y débiles (peso 0.5).
_STRONG_SIGNALS = (
    "clínica",
    "clinica",
    "hospital",
    "consultorio",
    "sanatorio",
    "laboratorio",
    "odontolog",
    "dental",
    "salud",
    "médic",
    "medico",
    "doctor",
    "dra.",
    "dr.",
    "enfermer",
    "pediatr",
    "cardiolog",
    "fisioterap",
    "imss",
    "issste",
    "paciente",
    "consulta médica",
    "especialista",
    "ambulancia",
    "quirófano",
    "quirofano",
    "unidad médica",
    "centro de salud",
)
_WEAK_SIGNALS = (
    "cita",
    "agenda",
    "tratamiento",
    "servicios médicos",
    "salud",
)


@dataclass
class MedicalVerdict:
    sector: str  # "medico" | "dudoso" | "no"
    confidence: float
    tipo_cliente: str | None = None
    especialidades: list[str] = field(default_factory=list)
    signals: list[str] = field(default_factory=list)


def normalize(text: str | None) -> str:
    value = unicodedata.normalize("NFKD", text or "")
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", value.strip().lower())


def detect_specialties(text: str | None) -> list[str]:
    blob = normalize(text)
    found: list[str] = []
    for needle, label in _SPECIALTIES:
        if needle in blob and label not in found:
            found.append(label)
    return found


def suggest_tipo(
    *,
    name: str | None = None,
    category: str | None = None,
    texts: list[str] | None = None,
) -> str | None:
    """Sugiere un valor del enum de Tipo de cliente (o ``None`` si no hay señal clara).

    Primero mira solo nombre/categoría (señal fuerte); si no alcanza, mira el
    texto amplio (snippets, fichas) como señal secundaria.
    """
    explicit = f"{normalize(name or '')} {normalize(category or '')}".strip()
    blob = normalize(" ".join(filter(None, [name, category, *(texts or [])])))
    for scope in (explicit, blob):
        if not scope:
            continue
        for needles, tipo in _TIPO_RULES:
            if any(needle in scope for needle in needles):
                return tipo
    return None


def classify(
    *,
    name: str | None = None,
    category: str | None = None,
    email: str | None = None,
    texts: list[str] | None = None,
    related_texts: list[str] | None = None,
) -> MedicalVerdict:
    """Decide si el lead es del ramo médico, con confianza y señales.

    ``related_texts`` (si se provee) es el subconjunto donde aparece el lead:
    se usa para derivar tipo/especialidad, evitando listados de terceros.
    """
    blob = normalize(" ".join(filter(None, [name, category, email, *(texts or [])])))
    derivation_blob = (
        normalize(" ".join(filter(None, [name, category, *(related_texts or [])])))
        if related_texts is not None
        else normalize(" ".join(filter(None, [name, category, *(texts or [])])))
    )
    score = 0.0
    signals: list[str] = []
    for needle in _STRONG_SIGNALS:
        if needle in blob:
            score += 2.0
            signals.append(needle)
    for needle in _WEAK_SIGNALS:
        if needle in blob and needle not in signals:
            score += 0.5
            signals.append(needle)
    specialties = detect_specialties(derivation_blob)
    if specialties:
        score += 1.0 * len(specialties)
        signals.extend(specialties)
    if email:
        local, _, domain = normalize(email).partition("@")
        local_medical = re.search(
            r"(^|[-._])(dr|dra|doctor|doctora|medic|medico|medical)([-._]|$)", local
        )
        domain_medical = re.search(
            r"(^|[-.])(clinica|hospital|salud|medic|dental|farmacia|laboratorio)([-.]|$)",
            domain,
        )
        if local_medical or domain_medical:
            score += 1.0
            signals.append("correo médico")

    tipo = suggest_tipo(
        name=name,
        category=category,
        texts=related_texts if related_texts is not None else texts,
    )
    if tipo is not None and tipo in MEDICAL_TIPOS:
        score += 2.0
        signals.append(f"tipo sugerido: {tipo}")

    if score >= 3.0:
        sector = "medico"
    elif score >= 1.0:
        sector = "dudoso"
    else:
        sector = "no"
    confidence = round(min(0.96, score / 6.0), 2)
    if sector == "no":
        confidence = round(max(0.5, 1.0 - confidence), 2)
    seen: list[str] = []
    for signal in signals:
        if signal not in seen:
            seen.append(signal)
    return MedicalVerdict(
        sector=sector,
        confidence=confidence,
        tipo_cliente=tipo,
        especialidades=specialties,
        signals=seen[:10],
    )
