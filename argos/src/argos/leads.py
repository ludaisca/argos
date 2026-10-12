"""Enriquecedor de leads (sección Personalizada).

Entra una lista de leads del CRM (nombre, correo, teléfono, empresa/clínica/hospital)
y sale una fila enriquecida con las columnas del CRM + validación de sector.

Fuentes por lead (todas sin login):
- **SearxNG** (instancia propia): web general, teléfonos, sitios, páginas de Facebook.
- **Google Maps** (scraping, opcional): ficha del lugar (categoría, dirección, teléfono).
- **Nominatim reverse**: dirección → Entidad (estado) y Ciudad.

Es incremental: escribe los resultados tras cada lead, así un lote largo se puede
cortar sin perder lo hecho.
"""

from __future__ import annotations

import csv
import datetime as dt
import io
import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from rich.console import Console

from argos import places as places_mod
from argos import searxng
from argos.config import ArgosConfig
from argos.errors import ArgosError, UsageError
from argos.models import Place
from argos.sectors import medico

_console = Console(stderr=True)

#: Columnas de salida (nombres del CRM + validación).
CRM_COLUMNS = [
    "Nombre",
    "Apellido",
    "Correo",
    "Teléfono",
    "Entidad",
    "Ciudad",
    "Tipo de cliente",
    "Especialidad",
    "Categoría",
    "Facebook",
    "Google Maps",
    "Observaciones",
    "Ramo médico",
    "Confianza",
    "Evidencias",
]

_EMAIL_RE = re.compile(r"[^@\s]+@[^@\s]+\.[A-Za-z]{2,}")
_PHONE_RE = re.compile(r"(?:\+?52[\s.-]?)?(?:\(?\d{2,3}\)?[\s.-]?)?\d{3,4}[\s.-]?\d{4}")
_COMPANY_HINT = re.compile(
    r"clinic|hospital|consultorio|dental|laborator|centro|salud|sanatorio|ambulanc|veterinar|salud",
    re.I,
)
_SOCIAL_BLOCK = ("/login", "/signup", "/help", "/policies", "/privacy", "/groups/", "/watch")


# --------------------------------------------------------------------------- #
# Modelos
# --------------------------------------------------------------------------- #


@dataclass
class Lead:
    nombre: str = ""
    correo: str = ""
    telefono: str = ""
    empresa: str = ""

    @property
    def label(self) -> str:
        return self.empresa or self.nombre or self.correo or self.telefono or "(lead)"


@dataclass
class EnrichedLead:
    lead: Lead
    sector: str = "dudoso"
    sector_confidence: float = 0.0
    tipo_cliente: str | None = None
    especialidad: str | None = None
    apellido: str | None = None
    telefono: str | None = None
    entidad: str | None = None
    ciudad: str | None = None
    facebook: str | None = None
    google_maps: str | None = None
    categoria: str | None = None
    observaciones: str = ""
    evidencia: list[str] = field(default_factory=list)
    queries: list[str] = field(default_factory=list)


@dataclass
class Sources:
    """Fuentes inyectables (tests) con sus defaults reales."""

    config: ArgosConfig
    searx_base: str
    use_gmaps: bool = True
    searx_fn: Callable[..., list[searxng.SearxResult]] = searxng.search
    places_fn: Callable[..., places_mod.PlacesResult] = places_mod.search
    reverse_fn: Callable[..., dict[str, str] | None] = places_mod.reverse_geocode


# --------------------------------------------------------------------------- #
# Entrada
# --------------------------------------------------------------------------- #


def _looks_like_phone(value: str) -> bool:
    digits = re.sub(r"\D", "", value)
    return 8 <= len(digits) <= 15 and len(digits) >= len(re.sub(r"[\s().-]", "", value)) - 2


def _lead_from_cells(cells: list[str]) -> Lead:
    """Asigna celdas sueltas por patrón (correo, teléfono, empresa, nombre)."""
    lead = Lead()
    for cell in cells:
        cell = cell.strip()
        if not cell:
            continue
        if not lead.correo and _EMAIL_RE.fullmatch(cell):
            lead.correo = cell
            continue
        if not lead.telefono and _looks_like_phone(cell):
            lead.telefono = cell
            continue
        if not lead.empresa and _COMPANY_HINT.search(cell):
            lead.empresa = cell
            continue
        if not lead.nombre:
            lead.nombre = cell
            continue
        if not lead.empresa:
            lead.empresa = cell
    return lead


_HEADER_ALIASES = {
    "nombre": ("nombre", "name", "nombre completo", "first name", "nombres"),
    "correo": ("correo", "email", "e-mail", "mail", "correo electronico", "correo electrónico"),
    "telefono": ("telefono", "teléfono", "phone", "celular", "whatsapp", "tel"),
    "empresa": (
        "empresa",
        "clinica",
        "clínica",
        "hospital",
        "company",
        "organizacion",
        "organización",
        "empresa/clinica/hospital",
    ),
}


def parse_leads(text: str) -> list[Lead]:
    """CSV/TSV con encabezados conocidos, o líneas sueltas detectadas por patrón."""
    cleaned = (text or "").strip()
    if not cleaned:
        return []
    lines = [line for line in cleaned.splitlines() if line.strip()]
    # Delimitador por línea: tab si está, si no coma (tolera archivos mixtos).
    rows: list[list[str]] = []
    for line in lines:
        delimiter = "\t" if "\t" in line else ","
        rows.append(next(csv.reader([line], delimiter=delimiter)))
    header_tokens = {medico.normalize(cell) for cell in rows[0]}
    has_header = any(
        token in header_tokens for aliases in _HEADER_ALIASES.values() for token in aliases
    )
    header_map: dict[str, int] | None = None
    leads: list[Lead] = []
    for index, cells in enumerate(rows):
        cells = [cell.strip() for cell in cells]
        if not any(cells):
            continue
        if index == 0 and has_header:
            header_map = {medico.normalize(cell): position for position, cell in enumerate(cells)}
            continue
        if header_map is not None:
            lead = Lead()
            for field_name, aliases in _HEADER_ALIASES.items():
                for alias in aliases:
                    position = header_map.get(alias)
                    if position is not None and position < len(cells):
                        setattr(lead, field_name, cells[position])
                        break
            if lead.nombre or lead.correo or lead.telefono or lead.empresa:
                leads.append(lead)
        else:
            lead = _lead_from_cells(cells)
            if lead.nombre or lead.correo or lead.telefono or lead.empresa:
                leads.append(lead)
    return leads


# --------------------------------------------------------------------------- #
# Enriquecimiento
# --------------------------------------------------------------------------- #


def _split_name(nombre: str) -> tuple[str, str | None]:
    tokens = nombre.split()
    if len(tokens) >= 2:
        return " ".join(tokens[:-1]), tokens[-1]
    return nombre, None


def _phone_from_texts(texts: list[str]) -> str | None:
    for text in texts:
        for match in _PHONE_RE.findall(text):
            digits = re.sub(r"\D", "", str(match))
            if 10 <= len(digits) <= 13:
                return str(match).strip()
    return None


def _facebook_from_hits(hits: list[searxng.SearxResult]) -> str | None:
    for hit in hits:
        url = hit.url.split("?")[0]
        if "facebook.com/" not in url:
            continue
        if any(block in url for block in _SOCIAL_BLOCK):
            continue
        if url.rstrip("/").endswith("facebook.com"):
            continue
        return url
    return None


def enrich_lead(lead: Lead, sources: Sources) -> EnrichedLead:
    """Enriquece un lead consultando las fuentes configuradas."""
    result = EnrichedLead(lead=lead)
    hits: list[searxng.SearxResult] = []
    texts: list[str] = []

    def run_query(query: str, limit: int = 6) -> None:
        result.queries.append(query)
        try:
            found = sources.searx_fn(query, base=sources.searx_base, limit=limit)
        except ArgosError as exc:
            _console.print(f"[yellow]  searx: {exc}[/yellow]")
            return
        hits.extend(found)
        for hit in found:
            texts.append(hit.title)
            texts.append(hit.snippet)

    empresa = lead.empresa.strip()
    nombre = lead.nombre.strip()
    if empresa:
        run_query(f'"{empresa}"')
        run_query(f'"{empresa}" (médico OR doctor OR clínica OR hospital OR especialista)')
        run_query(f'site:facebook.com "{empresa}"')
    if nombre:
        run_query(f'"{nombre}" (médico OR doctor OR clínica OR hospital OR especialista)')
        if not empresa:
            run_query(f'site:facebook.com "{nombre}"')
    if lead.telefono:
        run_query(f'"{lead.telefono}"', limit=4)
    if lead.correo:
        run_query(f'"{lead.correo}"', limit=4)

    result.facebook = _facebook_from_hits(hits)
    result.telefono = _phone_from_texts(texts) or (lead.telefono or None)

    # Google Maps: ficha del lugar (categoría, dirección, teléfono, link)
    place: Place | None = None
    query_place = empresa or nombre
    if sources.use_gmaps and query_place:
        try:
            gm = sources.places_fn(
                query_place,
                limit=3,
                provider="gmaps",
                config=sources.config,
                headless=True,
            )
            place = gm.places[0] if gm.places else None
        except ArgosError as exc:
            _console.print(f"[yellow]  gmaps: {exc}[/yellow]")
    if place is not None:
        texts.extend([place.name or "", place.category or "", place.address or ""])
        result.google_maps = place.url
        result.categoria = place.category
        result.telefono = result.telefono or place.phone
        if place.lat is not None and place.lon is not None:
            try:
                reverse = sources.reverse_fn(place.lat, place.lon)
            except ArgosError:
                reverse = None
            if reverse:
                result.entidad = reverse.get("state") or None
                result.ciudad = reverse.get("city") or None
        elif place.address:
            parts = [part.strip() for part in place.address.split(",") if part.strip()]
            if len(parts) >= 2:
                result.ciudad = parts[-2]
                result.entidad = parts[-1]

    verdict = medico.classify(
        name=(place.name if place else empresa) or nombre or None,
        category=place.category if place else None,
        email=lead.correo or None,
        texts=texts,
    )
    result.sector = verdict.sector
    result.sector_confidence = verdict.confidence
    result.especialidad = ", ".join(verdict.especialidades) or None
    if verdict.sector == "medico" and verdict.tipo_cliente:
        result.tipo_cliente = verdict.tipo_cliente
    elif verdict.sector == "no":
        result.tipo_cliente = medico.NO_RAMO

    _, apellido = _split_name(nombre)
    result.apellido = (
        apellido if (nombre and " " in nombre) else _apellido_from_hits(nombre, hits)
    )

    summary: list[str] = []
    if place is not None:
        detail = place.category or "s/categoría"
        if place.address:
            detail = f"{detail} · {place.address[:80]}"
        summary.append(f"Google Maps: {place.name} ({detail})")
    if result.facebook:
        summary.append(f"Facebook: {result.facebook}")
    if verdict.signals:
        summary.append("Señales: " + ", ".join(verdict.signals[:6]))
    summary.append(f"Ramo médico: {verdict.sector} (confianza {verdict.confidence:.2f})")
    result.observaciones = " · ".join(summary)
    seen_urls: list[str] = []
    for hit in hits:
        if hit.url not in seen_urls:
            seen_urls.append(hit.url)
    result.evidencia = seen_urls[:8]
    return result


def _apellido_from_hits(nombre: str, hits: list[searxng.SearxResult]) -> str | None:
    """Busca 'Dr. <Nombre> <Apellido>' o '<Nombre> <Apellido>' en títulos."""
    if not nombre:
        return None
    pattern = re.compile(
        rf"(?:dr[a]?\.?\s+)?{re.escape(nombre)}\s+([A-ZÁÉÍÓÚÑ][a-záéíóúñ]+)",
        re.IGNORECASE,
    )
    for hit in hits:
        match = pattern.search(hit.title)
        if match:
            return match.group(1)
    return None


# --------------------------------------------------------------------------- #
# Salida
# --------------------------------------------------------------------------- #


def to_row(enriched: EnrichedLead) -> dict[str, str]:
    return {
        "Nombre": enriched.lead.nombre,
        "Apellido": enriched.apellido or "",
        "Correo": enriched.lead.correo,
        "Teléfono": enriched.telefono or "",
        "Entidad": enriched.entidad or "",
        "Ciudad": enriched.ciudad or "",
        "Tipo de cliente": enriched.tipo_cliente or "",
        "Especialidad": enriched.especialidad or "",
        "Categoría": enriched.categoria or "",
        "Facebook": enriched.facebook or "",
        "Google Maps": enriched.google_maps or "",
        "Observaciones": enriched.observaciones,
        "Ramo médico": {"medico": "Sí", "dudoso": "Dudoso", "no": "No"}.get(
            enriched.sector, "Dudoso"
        ),
        "Confianza": f"{enriched.sector_confidence:.2f}",
        "Evidencias": " | ".join(enriched.evidencia[:5]),
    }


def write_outputs(
    enriched: list[EnrichedLead], out_dir: Path, *, config: ArgosConfig
) -> dict[str, Any]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = [to_row(item) for item in enriched]
    (out_dir / "leads.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    with (out_dir / "leads.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CRM_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)

    counts = {"medico": 0, "dudoso": 0, "no": 0}
    for item in enriched:
        counts[item.sector] = counts.get(item.sector, 0) + 1
    lines = [
        "# Enriquecimiento de leads — sector médico",
        "",
        f"Generado: {dt.datetime.now(dt.UTC).isoformat(timespec='seconds')} · "
        f"{len(enriched)} leads",
        "",
        f"- Ramo médico: **{counts['medico']}** · dudosos: {counts['dudoso']} · "
        f"no del ramo: {counts['no']}",
        f"- Con teléfono: {sum(1 for item in enriched if item.telefono)} · "
        f"con Google Maps: {sum(1 for item in enriched if item.google_maps)} · "
        f"con Facebook: {sum(1 for item in enriched if item.facebook)} · "
        f"con entidad/ciudad: {sum(1 for item in enriched if item.entidad or item.ciudad)}",
        "",
        "## Detalle",
        "",
    ]
    for item in enriched:
        lines.append(
            f"- **{item.lead.label}** → {item.sector} "
            f"({item.sector_confidence:.2f}) · tipo: {item.tipo_cliente or '—'} · "
            f"esp.: {item.especialidad or '—'}"
        )
    (out_dir / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {
        "dir": str(out_dir),
        "csv": str(out_dir / "leads.csv"),
        "json": str(out_dir / "leads.json"),
        "report": str(out_dir / "report.md"),
        "rows": len(rows),
        "counts": counts,
    }


def enrich_batch(
    leads: list[Lead],
    *,
    out_dir: Path,
    config: ArgosConfig,
    sector: str = "medico",
    use_gmaps: bool = True,
    limit: int | None = None,
    sources: Sources | None = None,
) -> dict[str, Any]:
    """Procesa el lote completo (incremental) y devuelve el resumen de salida."""
    if sector not in ("medico", "médico"):
        raise UsageError(
            f"sector desconocido: {sector!r}", hint="por ahora: medico"
        )
    if not leads:
        raise UsageError("no hay leads para procesar")
    if limit is not None:
        leads = leads[: max(1, limit)]
    sources = sources or Sources(
        config=config,
        searx_base=searxng.resolve_base(config),
        searx_fn=lambda *args, **kwargs: searxng.search(*args, **kwargs),
        places_fn=lambda *args, **kwargs: places_mod.search(*args, **kwargs),
        reverse_fn=lambda *args, **kwargs: places_mod.reverse_geocode(*args, **kwargs),
    )
    enriched: list[EnrichedLead] = []
    total = len(leads)
    for index, lead in enumerate(leads, 1):
        _console.print(f"[dim]({index}/{total}) {lead.label}[/dim]")
        enriched.append(enrich_lead(lead, sources))
        write_outputs(enriched, out_dir, config=config)
    summary = write_outputs(enriched, out_dir, config=config)
    return summary


def template_csv() -> str:
    """Plantilla de entrada para el CRM."""
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["Nombre", "Correo", "Teléfono", "Empresa"])
    writer.writerow(["Char Gipt", "chargipt01@gmail.com", "", ""])
    writer.writerow(["", "", "2221234567", "Clínica Dental Sonrisa Puebla"])
    return buffer.getvalue()
