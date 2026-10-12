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
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from rich.console import Console

from argos import bing, mexico, searxng
from argos import places as places_mod
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
_FB_SKIP = (
    "/posts/",
    "/permalink",
    "/photo",
    "/story.php",
    "/profile.php",
    "/reel",
    "/videos/",
)


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


DEFAULT_LEAD_SOURCES: dict[str, bool] = {
    "searxng": True,
    "bing": True,
    "facebook": True,
    "gmaps": True,
    "nominatim": True,
}
LEAD_SOURCES_KEY = "leads_sources"


def load_lead_sources(config: ArgosConfig) -> dict[str, bool]:
    """Fuentes activas de Personalizada (``leads_sources`` en la config)."""
    flags = dict(DEFAULT_LEAD_SOURCES)
    raw = config.get(LEAD_SOURCES_KEY)
    if isinstance(raw, dict):
        for key in flags:
            if isinstance(raw.get(key), bool):
                flags[key] = raw[key]
    return flags


@dataclass
class Sources:
    """Fuentes inyectables (tests) con sus defaults reales."""

    config: ArgosConfig
    searx_base: str
    use_searxng: bool = True
    use_bing: bool = True
    use_facebook: bool = True
    use_gmaps: bool = True
    use_nominatim: bool = True
    searx_fn: Callable[..., list[searxng.SearxResult]] = searxng.search
    bing_fn: Callable[..., list[searxng.SearxResult]] = bing.search
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


_JSON_NAME_KEYS = ("fullname", "full name", "nombre completo", "nombre", "nombres")
_JSON_EMAIL_KEYS = ("email", "correo", "correo electronico", "e-mail", "mail")
_JSON_PHONE_KEYS = ("phone", "telefono", "celular", "whatsapp", "movil", "tel")
_JSON_COMPANY_KEYS = (
    "empresa",
    "company",
    "organizacion",
    "negocio",
    "clinica",
    "hospital",
    "centro",
)
_JSON_PHASE_WORDS = {
    "no contactado",
    "contactado",
    "nuevo",
    "prospecto",
    "en proceso",
    "seguimiento",
    "cerrado",
    "perdido",
    "sin fase",
}


def _json_key(value: object) -> str:
    return re.sub(r"\s+", " ", mexico.fold(str(value))).strip()


def _json_scalar(item: dict[str, object], keys: tuple[str, ...]) -> str:
    for key, value in item.items():
        if _json_key(key) not in keys:
            continue
        if isinstance(value, bool) or not isinstance(value, (str, int, float)):
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


def _leads_from_json(text: str) -> list[Lead]:
    """Export de CRM (lista JSON o ``{consulta: [filas]}``) → leads."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return []
    items: list[object] = []
    if isinstance(data, list):
        items = list(data)
    elif isinstance(data, dict):
        candidates = [value for value in data.values() if isinstance(value, list)]
        if candidates:
            for candidate in candidates:
                items.extend(candidate)
        else:
            items = [data]
    leads: list[Lead] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        lead = Lead(
            nombre=_json_scalar(item, _JSON_NAME_KEYS),
            correo=_json_scalar(item, _JSON_EMAIL_KEYS),
            telefono=_json_scalar(item, _JSON_PHONE_KEYS),
            empresa=_json_scalar(item, _JSON_COMPANY_KEYS),
        )
        if not lead.nombre and not lead.empresa:
            generic = _json_scalar(item, ("name", "title"))
            if generic and _json_key(generic) not in _JSON_PHASE_WORDS:
                lead.nombre = generic
        if lead.nombre or lead.correo or lead.telefono or lead.empresa:
            leads.append(lead)
    return leads


def parse_leads(text: str) -> list[Lead]:
    """JSON del CRM, CSV/TSV con encabezados, o líneas sueltas detectadas por patrón."""
    cleaned = (text or "").strip()
    if not cleaned:
        return []
    if cleaned[0] in "[{":
        json_leads = _leads_from_json(cleaned)
        if json_leads:
            return json_leads
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


def _facebook_from_hits(hits: list[searxng.SearxResult], tokens: list[str]) -> str | None:
    """Página de Facebook del negocio/persona — nunca posts sueltos ni grupos.

    Con ``tokens`` (nombre/empresa normalizados), el slug de la página tiene que
    contener al menos uno: evita matches genéricos (un post que solo menciona el
    nombre, como el “feliz cumple Daniel” que enganchó a un lead real).
    """
    for hit in hits:
        url = hit.url.split("?")[0]
        if "facebook.com/" not in url:
            continue
        if any(block in url for block in _SOCIAL_BLOCK):
            continue
        if any(block in url for block in _FB_SKIP):
            continue
        if url.rstrip("/").endswith("facebook.com"):
            continue
        if tokens:
            trimmed = url.rstrip("/")
            slug = re.sub(r"[^a-z0-9]", "", trimmed.rsplit("/", 1)[-1].lower())
            if not any(token in slug for token in tokens):
                continue
        return url
    return None


def enrich_lead(lead: Lead, sources: Sources) -> EnrichedLead:
    """Enriquece un lead consultando las fuentes configuradas."""
    result = EnrichedLead(lead=lead)
    hits: list[searxng.SearxResult] = []
    mexican_hits: list[searxng.SearxResult] = []
    texts: list[str] = []  # solo de hits mexicanos (clasificación/teléfono)

    dropped_foreign = 0

    def run_query(query: str, limit: int = 6, *, retry_empty: bool = True) -> None:
        nonlocal dropped_foreign
        result.queries.append(query)
        found: list[searxng.SearxResult] = []
        rounds: list[str] = ["searxng"]
        if retry_empty and sources.use_bing:
            rounds.append("bing")
        source_used = rounds[0]
        for index, source_name in enumerate(rounds):
            try:
                if source_name == "bing":
                    found = sources.bing_fn(query, limit=limit)
                else:
                    found = sources.searx_fn(query, base=sources.searx_base, limit=limit)
            except ArgosError as exc:
                _console.print(f"[yellow]  {source_name}: {exc}[/yellow]")
                if index < len(rounds) - 1:
                    continue
                return
            source_used = source_name
            if found:
                break
            if index < len(rounds) - 1:
                _console.print(f"[dim]  {source_name}: 0 resultados; pruebo respaldo…[/dim]")
                time.sleep(3.0)
        verdicts = [
            (hit, mexico.hit_country(hit.url, hit.title, hit.snippet)) for hit in found
        ]
        kept = [(hit, verdict) for hit, verdict in verdicts if verdict != "foreign"]
        dropped = len(found) - len(kept)
        dropped_foreign += dropped
        extra = f" ({dropped} fuera de México, descartados)" if dropped else ""
        _console.print(
            f"[dim]  {source_used}: {len(kept)} resultados{extra} · {query[:70]}[/dim]"
        )
        for hit, verdict in kept:
            hits.append(hit)
            if verdict == "mx":
                mexican_hits.append(hit)
                texts.append(hit.title)
                texts.append(hit.snippet)

    empresa = lead.empresa.strip()
    nombre = lead.nombre.strip()
    if sources.use_searxng and empresa:
        run_query(f'"{empresa}"')
        run_query(f'"{empresa}" (médico OR doctor OR clínica OR hospital OR especialista)')
        if sources.use_facebook:
            run_query(f'site:facebook.com "{empresa}"')
    if sources.use_searxng and nombre:
        run_query(f'"{nombre}" (médico OR doctor OR clínica OR hospital OR especialista)')
        if not empresa and sources.use_facebook and len(nombre.split()) >= 2:
            run_query(f'site:facebook.com "{nombre}"')
    if sources.use_searxng and lead.telefono:
        run_query(f'"{lead.telefono}"', limit=4, retry_empty=False)
    if sources.use_searxng and lead.correo:
        run_query(f'"{lead.correo}"', limit=4, retry_empty=False)

    name_tokens = [t for t in medico.normalize(f"{empresa} {nombre}").split() if len(t) >= 4]
    slug_tokens = [t for t in medico.normalize(empresa or nombre).split() if len(t) >= 4]
    contact_tokens = [t for t in (lead.correo.lower(), lead.telefono.strip()) if t]

    result.facebook = _facebook_from_hits(hits, slug_tokens)
    result.telefono = _phone_from_texts(texts) or (lead.telefono or None)

    # Textos que pueden clasificar: hits MEXICANOS + los que contienen el correo/
    # teléfono del lead (identifican a la persona aunque el dominio no sea .mx).
    # Todo lo demás (páginas .com sin origen claro) queda fuera: "solo México".
    person_lead = not empresa and not _COMPANY_HINT.search(nombre)
    mx_ids = {id(hit) for hit in mexican_hits}
    pool: list[searxng.SearxResult] = []
    for hit in hits:
        haystack = f"{hit.title} {hit.snippet}".lower()
        if id(hit) in mx_ids or any(token in haystack for token in contact_tokens):
            pool.append(hit)

    # Dentro del pool: solo los hits donde aparece el nombre/empresa (o el correo/
    # teléfono). Evita que listados de terceros (directorios, PDFs) aporten
    # tipo/especialidad que no son del lead.
    related_texts: list[str] = []
    related_hits: list[searxng.SearxResult] = []
    for hit in pool:
        title_norm = medico.normalize(hit.title)
        haystack = f"{hit.title} {hit.snippet}".lower()
        hits_name = sum(1 for token in name_tokens if token in title_norm)
        hits_contact = any(token in haystack for token in contact_tokens)
        needed = 1 if len(name_tokens) <= 1 else 2
        if hits_contact or (name_tokens and hits_name >= needed):
            related_hits.append(hit)
            related_texts.append(hit.title)
            if not person_lead:
                related_texts.append(hit.snippet)

    # Google Maps: ficha del lugar (solo con empresa o nombre de institución; para
    # personas sueltas no aplica y ahorramos el intento).
    place: Place | None = None
    reverse: dict[str, str] | None = None
    query_place = empresa or nombre
    looks_institution = bool(_COMPANY_HINT.search(query_place))
    if sources.use_gmaps and query_place and (empresa or looks_institution):
        try:
            gm = sources.places_fn(
                f"{query_place} México",
                limit=3,
                provider="gmaps",
                config=sources.config,
                headless=True,
            )
            place = gm.places[0] if gm.places else None
        except ArgosError as exc:
            _console.print(f"[yellow]  gmaps: {exc}[/yellow]")
    if place is not None:
        # Solo México: coordenadas/dirección y, si está activo, Nominatim manda.
        if sources.use_nominatim and place.lat is not None and place.lon is not None:
            try:
                reverse = sources.reverse_fn(place.lat, place.lon)
            except ArgosError:
                reverse = None
        country_code = ((reverse or {}).get("country_code") or "").lower()
        verdict_place = mexico.place_country(place)
        if country_code and country_code != "mx":
            verdict_place = "foreign"
        if verdict_place == "foreign":
            _console.print(
                f"[yellow]  gmaps: ficha fuera de México, descartada "
                f"({place.address or place.name})[/yellow]"
            )
            dropped_foreign += 1
            place = None
            reverse = None
    if place is not None:
        texts.extend([place.name or "", place.category or "", place.address or ""])
        related_texts.extend([place.name or "", place.category or "", place.address or ""])
        result.google_maps = place.url
        result.categoria = place.category
        result.telefono = result.telefono or place.phone
        if reverse:
            result.entidad = reverse.get("state") or None
            result.ciudad = reverse.get("city") or None
        elif place.address:
            parts = [part.strip() for part in place.address.split(",") if part.strip()]
            if len(parts) >= 2:
                result.ciudad = parts[-2]
                result.entidad = parts[-1]

    _, apellido = _split_name(nombre)
    result.apellido = (
        apellido if (nombre and " " in nombre) else _apellido_from_hits(nombre, related_hits)
    )

    # Sin datos mexicanos (ni ficha MX ni página con el contacto del lead), no
    # afirmamos "no es del ramo": queda dudoso con la nota correspondiente.
    if not pool and place is None and not result.facebook:
        result.sector = "dudoso"
        result.sector_confidence = 0.1
        if not sources.use_searxng:
            reason = "SearxNG desactivado en Fuentes de búsqueda"
        elif dropped_foreign:
            reason = f"{dropped_foreign} resultados descartados por no ser de México"
        elif hits:
            reason = "solo hubo resultados sin origen mexicano claro"
        else:
            reason = "búsquedas vacías (SearxNG/Bing); reintentar más tarde"
        result.observaciones = f"Sin resultados de búsqueda ({reason})"
        return result

    # Resultados que no son verificables del lead (p. ej. una marca con el mismo
    # nombre): tampoco alcanzan para afirmar "no es del ramo".
    if not related_texts and place is None:
        result.sector = "dudoso"
        result.sector_confidence = 0.1
        parts = []
        if result.facebook:
            parts.append(f"Facebook: {result.facebook}")
        parts.append("Sin coincidencias claras del lead en México (resultados no verificables)")
        if dropped_foreign:
            parts.append(f"Solo México: {dropped_foreign} descartados de otros países")
        result.observaciones = " · ".join(parts)
        return result

    verdict = medico.classify(
        name=(place.name if place else empresa) or nombre or None,
        category=place.category if place else None,
        email=lead.correo or None,
        texts=texts,
        related_texts=related_texts,
    )
    result.sector = verdict.sector
    result.sector_confidence = verdict.confidence
    result.especialidad = ", ".join(verdict.especialidades) or None
    if verdict.sector == "medico" and verdict.tipo_cliente:
        result.tipo_cliente = verdict.tipo_cliente
    elif verdict.sector == "no":
        result.tipo_cliente = medico.NO_RAMO

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
    if dropped_foreign:
        summary.append(f"Solo México: {dropped_foreign} resultados descartados de otros países")
    summary.append(f"Ramo médico: {verdict.sector} (confianza {verdict.confidence:.2f})")
    result.observaciones = " · ".join(summary)
    seen_urls: list[str] = []
    if result.facebook:
        seen_urls.append(result.facebook)
    for hit in [*mexican_hits, *pool]:
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
    use_searxng: bool | None = None,
    use_bing: bool | None = None,
    use_facebook: bool | None = None,
    use_gmaps: bool | None = None,
    use_nominatim: bool | None = None,
    limit: int | None = None,
    batch_size: int | None = None,
    pause_seconds: float = 0.0,
    sleep_fn: Callable[[float], None] = time.sleep,
    sources: Sources | None = None,
) -> dict[str, Any]:
    """Procesa el lote completo (incremental) y devuelve el resumen de salida.

    Las fuentes activas salen de la config (``leads_sources``); los parámetros
    ``use_*`` fuerzan on/off solo para esta corrida. ``batch_size`` /
    ``pause_seconds`` procesa en tandas con pausas (SearxNG se satura con ráfagas).
    """
    if sector not in ("medico", "médico"):
        raise UsageError(
            f"sector desconocido: {sector!r}", hint="por ahora: medico"
        )
    if not leads:
        raise UsageError("no hay leads para procesar")
    if limit is not None:
        leads = leads[: max(1, limit)]
    if sources is None:
        flags = load_lead_sources(config)
        overrides = {
            "searxng": use_searxng,
            "bing": use_bing,
            "facebook": use_facebook,
            "gmaps": use_gmaps,
            "nominatim": use_nominatim,
        }
        for key, value in overrides.items():
            if value is not None:
                flags[key] = value
        sources = Sources(
            config=config,
            searx_base=searxng.resolve_base(config),
            use_searxng=flags["searxng"],
            use_bing=flags["bing"],
            use_facebook=flags["facebook"],
            use_gmaps=flags["gmaps"],
            use_nominatim=flags["nominatim"],
            searx_fn=lambda *args, **kwargs: searxng.search(*args, **kwargs),
            bing_fn=lambda *args, **kwargs: bing.search(*args, **kwargs),
            places_fn=lambda *args, **kwargs: places_mod.search(*args, **kwargs),
            reverse_fn=lambda *args, **kwargs: places_mod.reverse_geocode(*args, **kwargs),
        )
    enriched: list[EnrichedLead] = []
    total = len(leads)
    for index, lead in enumerate(leads, 1):
        if (
            batch_size
            and batch_size > 0
            and index > 1
            and (index - 1) % batch_size == 0
            and pause_seconds > 0
        ):
            tanda = (index - 1) // batch_size
            _console.print(
                f"[dim]pausa de {pause_seconds:.0f}s antes de la tanda {tanda + 1} "
                f"(SearxNG respira)…[/dim]"
            )
            sleep_fn(pause_seconds)
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
