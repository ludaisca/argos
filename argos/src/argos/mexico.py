"""Filtro México-only para el enriquecimiento de leads.

Regla dura: a un lead solo se le suma información de México. Los resultados de
otros países (Chile, Colombia, España, EE. UU., etc.) se descartan ANTES de
aportar tipo, contacto, especialidad, entidad o evidencia.

Criterios, en orden:
1. Dominio: ``.mx`` (y subdominios ``mx.`` de sitios multicampo) = México;
   ccTLD de otro país (``.cl``, ``.co``, ``.es``…) = extranjero.
2. Texto (título/snippet/dirección): estados y ciudades mexicanas vs países y
   ciudades inequívocas de otros países.
3. Coordenadas: caja envolvente de México; fuera = extranjero.
4. Nominatim (cuando está activo): ``country_code == "mx"`` manda.
"""

from __future__ import annotations

import re
import unicodedata
from typing import TYPE_CHECKING
from urllib.parse import urlparse

if TYPE_CHECKING:  # pragma: no cover
    from argos.models import Place
    from argos.searxng import SearxResult

# Caja envolvente de México (aproximada: incluye Baja California y el sureste).
LAT_MIN, LAT_MAX = 14.53, 32.72
LON_MIN, LON_MAX = -118.37, -86.71

# ccTLD / sufijos de host que pertenecen a otro país.
FOREIGN_SUFFIXES = (
    ".cl",
    ".co",
    ".ar",
    ".pe",
    ".ec",
    ".ve",
    ".uy",
    ".py",
    ".bo",
    ".cr",
    ".pa",
    ".gt",
    ".sv",
    ".hn",
    ".ni",
    ".do",
    ".cu",
    ".es",
    ".br",
    ".us",
    ".uk",
    ".pt",
    ".de",
    ".fr",
    ".it",
    ".edu",
)

# Sitios con subdominio/versión por país (mx.linkedin.com vs cl.linkedin.com).
MULTICAMPO = ("linkedin.com", "facebook.com", "indeed.com", "doctoralia.com", "computrabajo.com")
FOREIGN_SUBDOMAINS = frozenset(
    [
        "cl",
        "co",
        "ar",
        "pe",
        "ec",
        "ve",
        "uy",
        "py",
        "bo",
        "cr",
        "pa",
        "gt",
        "sv",
        "hn",
        "ni",
        "do",
        "cu",
        "es",
        "br",
        "us",
        "uk",
    ]
)

MEXICO_MARKERS = (
    "méxico",
    "mexico",
    "cdmx",
    "ciudad de mexico",
    "guadalajara",
    "monterrey",
    "puebla",
    "queretaro",
    "merida",
    "tijuana",
    "toluca",
    "cancun",
    "jalisco",
    "nuevo leon",
    "yucatan",
    "sonora",
    "sinaloa",
    "chihuahua",
    "coahuila",
    "tamaulipas",
    "veracruz",
    "oaxaca",
    "chiapas",
    "tabasco",
    "campeche",
    "quintana roo",
    "michoacan",
    "guanajuato",
    "aguascalientes",
    "zacatecas",
    "nayarit",
    "colima",
    "tlaxcala",
    "morelos",
    "baja california",
    "san luis potosi",
    "estado de mexico",
    "edomex",
    "imss",
    "issste",
    "gob.mx",
    "jal.",
    "n.l.",
    "gto.",
)

FOREIGN_MARKERS = (
    "chile",
    "colombia",
    "argentina",
    "peru",
    "ecuador",
    "bolivia",
    "venezuela",
    "paraguay",
    "uruguay",
    "guatemala",
    "honduras",
    "el salvador",
    "nicaragua",
    "costa rica",
    "panama",
    " cuba",
    "republica dominicana",
    "espana",
    "brasil",
    "brazil",
    "portugal",
    "estados unidos",
    "ee. uu",
    "eeuu",
    "bogota",
    "medellin",
    "santiago de chile",
    "buenos aires",
    "guayaquil",
    "montevideo",
    "asuncion",
    "madrid",
    "barcelona",
    "sao paulo",
    "rio de janeiro",
)


def fold(value: str) -> str:
    """minúsculas + sin acentos, para comparar marcadores."""
    lowered = value.lower()
    decomposed = unicodedata.normalize("NFKD", lowered)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


_MEXICO_FOLDED = tuple(fold(marker) for marker in MEXICO_MARKERS)
_FOREIGN_FOLDED = tuple(fold(marker) for marker in FOREIGN_MARKERS)


def host_of(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    return re.sub(r"^www\d*\.", "", host)


def url_country(url: str) -> str:
    """``mx`` / ``foreign`` / ``unknown`` según el dominio."""
    host = host_of(url)
    if not host:
        return "unknown"
    first = host.split(".")[0]
    if first == "mx" and host.endswith(tuple(f".{site}" for site in MULTICAMPO)):
        return "mx"
    if first in FOREIGN_SUBDOMAINS and host.endswith(MULTICAMPO):
        return "foreign"
    if host.endswith(".mx"):
        return "mx"
    return "foreign" if host.endswith(FOREIGN_SUFFIXES) else "unknown"


def text_country(text: str) -> str:
    """``mx`` / ``foreign`` / ``unknown`` según menciones de país/estado/ciudad."""
    folded = fold(text)
    has_mx = any(marker in folded for marker in _MEXICO_FOLDED)
    has_foreign = any(marker in folded for marker in _FOREIGN_FOLDED)
    if has_mx and not has_foreign:
        return "mx"
    if has_foreign and not has_mx:
        return "foreign"
    return "unknown"


def hit_country(title_or_url: str, title: str = "", snippet: str = "") -> str:
    """País de un resultado de búsqueda (URL primero; si no, título/snippet)."""
    by_url = url_country(title_or_url)
    if by_url != "unknown":
        return by_url
    return text_country(f"{title} {snippet}")


def coords_in_mexico(lat: float, lon: float) -> bool:
    return LAT_MIN <= lat <= LAT_MAX and LON_MIN <= lon <= LON_MAX


def place_country(place: Place) -> str:
    """País de una ficha de lugares: coordenadas si hay, si no la dirección."""
    lat = getattr(place, "lat", None)
    lon = getattr(place, "lon", None)
    if lat is not None and lon is not None:
        return "mx" if coords_in_mexico(float(lat), float(lon)) else "foreign"
    name = str(getattr(place, "name", "") or "")
    address = str(getattr(place, "address", "") or "")
    return text_country(f"{name} {address}")


def hit_is_foreign(hit: SearxResult) -> bool:
    return hit_country(hit.url, hit.title, hit.snippet) == "foreign"
