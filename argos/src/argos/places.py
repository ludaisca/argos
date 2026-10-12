"""Búsqueda de lugares sin costo: OpenStreetMap (Nominatim + Overpass) y Google Maps.

- **OSM** (``provider="osm"``, default): sin API key y sin pagos. Nominatim para
  ubicar la zona y Overpass para listar POIs por categoría o nombre dentro de un
  radio. Se respeta la política de uso de Nominatim (≤ 1 req/s) con un throttle
  interno y un ``User-Agent`` identificable.
- **Google Maps** (``provider="gmaps"``): scraping con Playwright (misma
  maquinaria anti-detección que FB/IG), best-effort: nombre, rating, reseñas,
  categoría, dirección y teléfono del panel de resultados.

No toca la cuota de Instagram/Facebook: usa su propio bucket diario (``places``).
"""

from __future__ import annotations

import hashlib
import math
import re
import time
import unicodedata
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote_plus

import requests
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright

from argos.browser.launch import launch_context
from argos.config import ArgosConfig
from argos.errors import ArgosError, UsageError
from argos.models import Place

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
OVERPASS_ENDPOINTS = (
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
)
PHOTON_URL = "https://photon.komoot.io/api/"
PHOTON_MAX_LIMIT = 50
USER_AGENT = "Argos/0.1 (herramienta personal de investigacion; uso local y de bajo volumen)"
PROVIDERS = ("osm", "gmaps")

_THROTTLE_SECONDS = 1.1
_last_request_at = 0.0


@dataclass(frozen=True)
class GeoPoint:
    label: str
    lat: float
    lon: float


@dataclass
class PlacesResult:
    places: list[Place]
    actions: int = 1
    detail: str = ""
    center: GeoPoint | None = None


# --------------------------------------------------------------------------- #
# Categorías (palabra en es/en → filtros Overpass)
# --------------------------------------------------------------------------- #

_RAW_CATEGORIES: dict[str, list[str]] = {
    "restaurante|restaurant|resto|comida|food|fondita": ['["amenity"="restaurant"]'],
    "cafe|cafeteria|coffee|coffee shop|starbucks": ['["amenity"="cafe"]'],
    "bar|cantina|cerveza|pub": ['["amenity"="bar"]', '["amenity"="pub"]'],
    "panaderia|bakery|pan": ['["shop"="bakery"]'],
    "pasteleria|reposteria|cake": ['["shop"="pastry"]', '["shop"="confectionery"]'],
    "pizza|pizzeria": [
        '["amenity"="restaurant"]["cuisine"~"pizza",i]',
        '["amenity"="fast_food"]["cuisine"~"pizza",i]',
    ],
    "sushi": ['["amenity"="restaurant"]["cuisine"~"sushi",i]'],
    "hamburguesa|burger|hamburguesas": [
        '["amenity"="fast_food"]["cuisine"~"burger",i]',
        '["amenity"="restaurant"]["cuisine"~"burger",i]',
    ],
    "tacos|taqueria": ['["amenity"="restaurant"]["cuisine"~"taco",i]', '["amenity"="fast_food"]'],
    "farmacia|pharmacy": ['["amenity"="pharmacy"]'],
    "hospital|clinica|clinic": ['["amenity"="hospital"]', '["amenity"="clinic"]'],
    "dentista|dentist|dental": ['["amenity"="dentist"]', '["healthcare"="dentist"]'],
    "doctor|medico|consultorio": ['["amenity"="doctors"]', '["amenity"="clinic"]'],
    "veterinaria|vet|veterinario": ['["amenity"="veterinary"]'],
    "gimnasio|gym|fitness": ['["leisure"="fitness_centre"]'],
    "hotel|hostal|hostal|posada|hospedaje": [
        '["tourism"="hotel"]',
        '["tourism"="hostel"]',
        '["tourism"="guest_house"]',
    ],
    "motel": ['["tourism"="motel"]'],
    "banco|bank": ['["amenity"="bank"]'],
    "cajero|atm": ['["amenity"="atm"]'],
    "supermercado|supermarket|soriana|walmart": ['["shop"="supermarket"]'],
    "tienda|abarrotes|conveniencia": ['["shop"="convenience"]', '["shop"="greengrocer"]'],
    "ferreteria|hardware": ['["shop"="hardware"]', '["shop"="doityourself"]'],
    "papeleria|stationery": ['["shop"="stationery"]'],
    "ropa|clothing|boutique": ['["shop"="clothes"]'],
    "zapateria|zapatos|shoes": ['["shop"="shoes"]'],
    "muebles|furniture": ['["shop"="furniture"]'],
    "celular|celulares|telefono|phone": ['["shop"="mobile_phone"]'],
    "computadora|computadoras|computers|informatica": ['["shop"="computer"]'],
    "gasolina|gasolinera|gas station|fuel|pemex": ['["amenity"="fuel"]'],
    "estacionamiento|parking": ['["amenity"="parking"]'],
    "escuela|school|colegio": ['["amenity"="school"]'],
    "universidad|university": ['["amenity"="university"]'],
    "guarderia|kinder": ['["amenity"="kindergarten"]'],
    "iglesia|church|templo": ['["amenity"="place_of_worship"]'],
    "parque|park": ['["leisure"="park"]'],
    "plaza comercial|mall|centro comercial": ['["shop"="mall"]'],
    "cine|cinema": ['["amenity"="cinema"]'],
    "teatro|theatre": ['["amenity"="theatre"]'],
    "museo|museum": ['["tourism"="museum"]'],
    "biblioteca|library": ['["amenity"="library"]'],
    "estetica|salon de belleza|beauty": ['["shop"="beauty"]'],
    "barberia|barber|peluqueria": ['["shop"="hairdresser"]'],
    "lavanderia|laundry": ['["shop"="laundry"]'],
    "taller mecanico|car repair|mecanico": ['["shop"="car_repair"]'],
    "refaccionaria|car parts|autopartes": ['["shop"="car_parts"]'],
    "agencia de viajes|travel": ['["shop"="travel_agency"]'],
    "inmobiliaria|estate agent": ['["office"="estate_agent"]'],
    "notaria|notary": ['["office"="notary"]'],
    "contador|accountant": ['["office"="accountant"]'],
    "abogado|lawyer|despacho": ['["office"="lawyer"]'],
    "software|desarrollo|startup": ['["office"="it"]', '["office"="company"]'],
}


def _normalize(value: str) -> str:
    text = unicodedata.normalize("NFKD", value or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", text.strip().lower())


_CATEGORY_LOOKUP: dict[str, list[str]] = {}
for _keys, _filters in _RAW_CATEGORIES.items():
    for _key in _keys.split("|"):
        _normalized = _normalize(_key)
        for _variant in (_normalized, f"{_normalized}s", f"{_normalized}es"):
            _CATEGORY_LOOKUP.setdefault(_variant, _filters)


def category_filters(query: str) -> list[str]:
    """Filtros Overpass para una consulta: categoría conocida o búsqueda por nombre."""
    normalized = _normalize(query)
    if normalized in _CATEGORY_LOOKUP:
        return _CATEGORY_LOOKUP[normalized]
    escaped = re.escape(query.strip())
    return [f'["name"~"{escaped}",i]']


# --------------------------------------------------------------------------- #
# HTTP helpers (throttled) — separados para tests
# --------------------------------------------------------------------------- #


def _throttle() -> None:
    global _last_request_at
    wait = _last_request_at + _THROTTLE_SECONDS - time.monotonic()
    if wait > 0:
        time.sleep(wait)
    _last_request_at = time.monotonic()


def _get_json(
    url: str, params: dict[str, Any] | list[tuple[str, str]], *, timeout: int
) -> Any:
    _throttle()
    try:
        response = requests.get(
            url, params=params, headers={"User-Agent": USER_AGENT}, timeout=timeout
        )
    except requests.RequestException as exc:
        raise ArgosError(f"falló la conexión a {url}: {exc}") from exc
    if response.status_code == 429:
        raise ArgosError(f"{url} limitó las consultas (HTTP 429)", hint="esperá un rato")
    if not response.ok:
        raise ArgosError(f"{url} devolvió HTTP {response.status_code}")
    try:
        return response.json()
    except ValueError as exc:
        raise ArgosError(f"{url} no devolvió JSON: {exc}") from exc


def _post_form(
    url: str, payload: dict[str, Any], *, timeout: int, connect_timeout: float = 8.0
) -> Any:
    _throttle()
    try:
        response = requests.post(
            url,
            data=payload,
            headers={"User-Agent": USER_AGENT},
            timeout=(connect_timeout, timeout),
        )
    except requests.RequestException as exc:
        raise ArgosError(f"falló la conexión a {url}: {exc}") from exc
    if response.status_code == 429:
        raise ArgosError(f"{url} limitó las consultas (HTTP 429)", hint="esperá un rato")
    if not response.ok:
        raise ArgosError(f"{url} devolvió HTTP {response.status_code}")
    try:
        return response.json()
    except ValueError as exc:
        raise ArgosError(f"{url} no devolvió JSON: {exc}") from exc


# --------------------------------------------------------------------------- #
# Nominatim (geocoding y búsqueda directa por nombre)
# --------------------------------------------------------------------------- #


_PLACE_RANKS = (
    "city",
    "town",
    "municipality",
    "village",
    "suburb",
    "quarter",
    "neighbourhood",
    "city_district",
    "borough",
    "district",
)


def geocode(query: str, *, timeout: int = 30) -> GeoPoint | None:
    """Ubica una zona por texto (``Puebla, MX`` → lat/lon).

    Nominatim suele devolver primero el *estado* para nombres ambiguos; se piden
    varios candidatos y se prefiere el que sea una ciudad/colonia/barrio.
    """
    data = _get_json(
        NOMINATIM_URL,
        {
            "q": query,
            "format": "jsonv2",
            "limit": 5,
            "addressdetails": 1,
            "accept-language": "es",
        },
        timeout=timeout,
    )
    if not isinstance(data, list) or not data:
        return None

    def rank(item: dict[str, Any]) -> int:
        kind = str(item.get("addresstype") or item.get("type") or "").lower()
        try:
            return _PLACE_RANKS.index(kind)
        except ValueError:
            return len(_PLACE_RANKS)

    first = min(data, key=rank)
    try:
        return GeoPoint(
            label=str(first.get("display_name") or query),
            lat=float(first["lat"]),
            lon=float(first["lon"]),
        )
    except (KeyError, TypeError, ValueError):
        return None


def _nominatim_places(query: str, *, limit: int, timeout: int) -> list[Place]:
    data = _get_json(
        NOMINATIM_URL,
        {
            "q": query,
            "format": "jsonv2",
            "limit": limit,
            "addressdetails": 1,
            "accept-language": "es",
        },
        timeout=timeout,
    )
    places: list[Place] = []
    if not isinstance(data, list):
        return places
    for item in data:
        try:
            osm_type = str(item.get("osm_type") or "node")
            osm_id = str(item.get("osm_id") or "")
            lat = item.get("lat")
            lon = item.get("lon")
            label = str(item.get("display_name") or "")
            name = str(item.get("name") or (label.split(",")[0] if label else "")).strip()
            if not name:
                continue
            places.append(
                Place(
                    source="osm",
                    id=f"{osm_type}/{osm_id}",
                    name=name[:120],
                    category=str(item.get("type") or "") or None,
                    address=label[:200] or None,
                    lat=float(lat) if lat not in (None, "") else None,
                    lon=float(lon) if lon not in (None, "") else None,
                    url=f"https://www.openstreetmap.org/{osm_type}/{osm_id}",
                    query=query,
                )
            )
        except (TypeError, ValueError):
            continue
    return places


# --------------------------------------------------------------------------- #
# Overpass (POIs por categoría o nombre en un radio)
# --------------------------------------------------------------------------- #


def _overpass_elements(
    filters: list[str],
    center: GeoPoint,
    radius_km: float,
    *,
    timeout: int,
    max_results: int = 80,
) -> list[dict[str, Any]]:
    radius_m = int(max(200.0, radius_km * 1000.0))
    parts = "".join(
        f"nwr{flt}(around:{radius_m},{center.lat:.6f},{center.lon:.6f});" for flt in filters
    )
    query = f"[out:json][timeout:{max(10, timeout - 5)}];({parts});out center {max_results};"
    endpoints: list[str] = []
    for endpoint in OVERPASS_ENDPOINTS:
        endpoints.append(endpoint)
        if endpoint == OVERPASS_ENDPOINTS[0]:
            endpoints.append(endpoint)  # los 504 del primario suelen ser transitorios
    last_error: ArgosError | None = None
    primary = OVERPASS_ENDPOINTS[0]
    endpoints = [primary, primary, primary, *OVERPASS_ENDPOINTS[1:]]
    for endpoint in endpoints:
        endpoint_timeout = timeout if endpoint == primary else min(timeout, 15)
        try:
            data = _post_form(endpoint, {"data": query}, timeout=endpoint_timeout)
        except ArgosError as exc:
            last_error = exc
            time.sleep(1.2)
            continue
        if isinstance(data, dict) and "elements" in data:
            return list(data.get("elements") or [])
    if last_error is not None:
        raise last_error
    return []


def _format_address(tags: dict[str, Any]) -> str | None:
    street = str(tags.get("addr:street") or "").strip()
    number = str(tags.get("addr:housenumber") or "").strip()
    city = str(tags.get("addr:city") or tags.get("addr:town") or "").strip()
    parts = []
    if street:
        parts.append(f"{street} {number}".strip())
    if city:
        parts.append(city)
    if not parts:
        full = str(tags.get("addr:full") or "").strip()
        return full[:200] or None
    return ", ".join(parts)[:200]


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    )
    return 2 * radius * math.asin(math.sqrt(a))


def _element_to_place(
    element: dict[str, Any],
    *,
    center: GeoPoint,
    query: str,
    location: str | None,
) -> Place | None:
    tags = element.get("tags") or {}
    name = str(tags.get("name") or tags.get("operator") or "").strip()
    if not name:
        return None
    if element.get("type") == "node":
        lat, lon = element.get("lat"), element.get("lon")
    else:
        center_data = element.get("center") or {}
        lat, lon = center_data.get("lat"), center_data.get("lon")
    distance = None
    if lat is not None and lon is not None:
        try:
            distance = round(
                _haversine_km(center.lat, center.lon, float(lat), float(lon)), 2
            )
        except (TypeError, ValueError):
            distance = None
    category = next(
        (
            str(tags[key])
            for key in ("amenity", "shop", "tourism", "leisure", "office", "healthcare", "craft")
            if tags.get(key)
        ),
        None,
    )
    osm_type = str(element.get("type") or "node")
    osm_id = str(element.get("id") or "")
    return Place(
        source="osm",
        id=f"{osm_type}/{osm_id}",
        name=name[:120],
        category=category,
        address=_format_address(tags),
        phone=str(tags.get("phone") or tags.get("contact:phone") or "")[:60] or None,
        website=str(tags.get("website") or tags.get("contact:website") or "")[:200] or None,
        opening_hours=str(tags.get("opening_hours") or "")[:120] or None,
        lat=float(lat) if lat is not None else None,
        lon=float(lon) if lon is not None else None,
        distance_km=distance,
        query=query,
        location=location,
        url=f"https://www.openstreetmap.org/{osm_type}/{osm_id}",
    )


def _photon_places(
    query: str,
    *,
    center: GeoPoint,
    radius_km: float,
    limit: int,
    timeout: int,
) -> list[Place]:
    """Respaldo cuando Overpass no responde: Photon (komoot) con sesgo geográfico."""
    params: list[tuple[str, str]] = [
        ("lat", f"{center.lat:.6f}"),
        ("lon", f"{center.lon:.6f}"),
        ("limit", str(min(PHOTON_MAX_LIMIT, max(limit * 2, limit)))),
    ]
    osm_tags: list[str] = []
    for flt in category_filters(query):
        match = re.search(r'\["([^"]+)"="([^"]+)"\]', flt)
        if match:
            osm_tags.append(f"{match.group(1)}:{match.group(2)}")
    if osm_tags:
        params.extend(("osm_tag", tag) for tag in osm_tags)
    else:
        params.append(("q", query))

    data = _get_json(PHOTON_URL, params, timeout=timeout)
    features = data.get("features") if isinstance(data, dict) else None
    places: list[Place] = []
    for feature in features or []:
        if not isinstance(feature, dict):
            continue
        props = feature.get("properties") or {}
        geometry = feature.get("geometry") or {}
        coords = geometry.get("coordinates") or []
        name = str(props.get("name") or "").strip()
        if not name:
            continue
        lat = lon = None
        if isinstance(coords, list) and len(coords) >= 2:
            try:
                lon, lat = float(coords[0]), float(coords[1])
            except (TypeError, ValueError):
                lat = lon = None
        distance = None
        if lat is not None and lon is not None:
            distance = round(_haversine_km(center.lat, center.lon, lat, lon), 2)
            if distance > radius_km * 1.25:
                continue
        osm_kind = {"N": "node", "W": "way", "R": "relation"}.get(
            str(props.get("osm_type") or "N").upper(), "node"
        )
        osm_id = str(props.get("osm_id") or "")
        street = " ".join(
            filter(
                None,
                [
                    str(props.get("street") or "").strip(),
                    str(props.get("housenumber") or "").strip(),
                ],
            )
        ).strip()
        city = str(props.get("city") or "").strip()
        address = ", ".join(part for part in (street, city) if part) or None
        places.append(
            Place(
                source="osm",
                id=f"{osm_kind}/{osm_id}" if osm_id else f"photon/{name[:40]}",
                name=name[:120],
                category=str(props.get("osm_value") or "") or None,
                address=address[:200] if address else None,
                lat=lat,
                lon=lon,
                distance_km=distance,
                query=query,
                location=center.label,
                url=f"https://www.openstreetmap.org/{osm_kind}/{osm_id}" if osm_id else None,
            )
        )
    return places


def _search_osm(
    query: str,
    *,
    location: str | None,
    radius_km: float,
    limit: int,
    timeout: int,
) -> PlacesResult:
    if not location:
        places = _nominatim_places(query, limit=limit, timeout=timeout)
        return PlacesResult(
            places=places[:limit],
            actions=1,
            detail=f"{len(places[:limit])} lugares (Nominatim: {query!r})",
        )

    center = geocode(location, timeout=timeout)
    if center is None:
        raise ArgosError(
            f"no pude ubicar la zona {location!r}",
            hint="probá con 'Ciudad, País' (ej: 'Puebla, MX')",
        )
    elements: list[dict[str, Any]] = []
    found: list[Place] = []
    source_label = "Overpass"
    try:
        elements = _overpass_elements(
            category_filters(query), center, radius_km, timeout=timeout
        )
    except ArgosError as overpass_error:
        # Overpass a veces devuelve 504 cuando está saturado: Photon es el respaldo.
        try:
            found = _photon_places(
                query, center=center, radius_km=radius_km, limit=limit, timeout=timeout
            )
        except ArgosError:
            raise overpass_error from None
        source_label = "Photon (respaldo de Overpass)"
    else:
        for element in elements:
            place = _element_to_place(
                element, center=center, query=query, location=location
            )
            if place is not None:
                found.append(place)

    found.sort(key=lambda place: place.distance_km if place.distance_km is not None else 1e9)
    found = found[:limit]
    return PlacesResult(
        places=found,
        actions=2,
        center=center,
        detail=(
            f"{len(found)} lugares de {query!r} en {radius_km:g} km "
            f"alrededor de {center.label[:60]} · {source_label}"
        ),
    )


# --------------------------------------------------------------------------- #
# Google Maps (scraping best-effort)
# --------------------------------------------------------------------------- #

_GMAPS_EXTRACT_JS = """
() => {
  const feed = document.querySelector('div[role="feed"]');
  if (!feed) return [];
  const cards = [...feed.querySelectorAll(':scope > div')];
  const out = [];
  for (const card of cards) {
    const a = card.querySelector('a[href*="/maps/place/"]');
    if (!a) continue;
    const label = (a.getAttribute('aria-label') || a.textContent || '').trim();
    const ratingLabel = [...card.querySelectorAll('[aria-label]')]
      .map(el => el.getAttribute('aria-label') || '')
      .find(text => /estrellas|stars/i.test(text)) || '';
    out.push({
      name: label,
      url: a.href,
      text: (card.innerText || '').trim(),
      rating_label: ratingLabel,
    });
  }
  return out;
}
"""

_STATUS_WORDS = ("abierto", "cerrado", "abre", "cierra", "abrirá")


def _gmaps_rows_to_places(
    rows: list[dict[str, Any]],
    *,
    query: str | None = None,
    location: str | None = None,
) -> list[Place]:
    places: list[Place] = []
    for row in rows:
        name = str(row.get("name") or "").strip()
        text = str(row.get("text") or "")
        url = str(row.get("url") or "") or None
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if not name and lines:
            name = lines[0]
        if not name:
            continue

        rating = None
        reviews = None
        rating_label = str(row.get("rating_label") or "")
        match = re.search(r"(\d[.,]\d)", rating_label)
        if match:
            try:
                rating = float(match.group(1).replace(",", "."))
            except ValueError:
                rating = None
        reviews_match = re.search(
            r"([\d.,]+)\s*(?:reseñas|reviews)", rating_label, re.IGNORECASE
        )
        if reviews_match:
            reviews = int(re.sub(r"[^\d]", "", reviews_match.group(1)) or "0")
        if rating is None:
            match = re.search(r"(\d[.,]\d)\s*\(([\d.,]+)\)", text)
            if match:
                try:
                    rating = float(match.group(1).replace(",", "."))
                    reviews = int(re.sub(r"[^\d]", "", match.group(2)) or "0")
                except ValueError:
                    rating = None
        if rating is None:
            standalone = next(
                (line for line in lines if re.fullmatch(r"\d[.,]\d", line)), None
            )
            if standalone is not None:
                try:
                    rating = float(standalone.replace(",", "."))
                except ValueError:
                    rating = None

        phone = None
        phone_match = re.search(r"(\+?\d[\d\s\-()]{6,}\d)", text)
        if phone_match:
            phone = phone_match.group(1).strip()[:60]

        candidates = [
            line
            for line in lines
            if line != name
            and not re.match(r"^\d[.,]\d", line)
            and not any(line.lower().startswith(word) for word in _STATUS_WORDS)
            and not re.match(r"^\+?\d[\d\s\-()]{6,}$", line)
        ]

        # Google suele poner "Categoría · Dirección" en una sola línea.
        category = None
        address = None
        for line in candidates:
            pieces = [piece.strip() for piece in line.split("·") if piece.strip()]
            for position, piece in enumerate(pieces):
                looks_like_address = bool(re.search(r"\d", piece)) or "," in piece
                if position == 0 and category is None and not looks_like_address:
                    category = piece[:60]
                    continue
                if address is None and looks_like_address:
                    address = piece[:160]
        if category is None and candidates:
            category = candidates[0][:60]
        if address is None:
            for line in candidates:
                if re.search(r"\d", line) or "," in line:
                    address = line[:160]
                    break

        hours = None
        hours_match = re.search(r"((?:Abierto|Cerrado)[^\n]{0,70})", text)
        if hours_match:
            hours = hours_match.group(1).strip()[:120]

        digest = hashlib.sha1(f"{name}|{address or ''}".encode()).hexdigest()[:16]
        places.append(
            Place(
                source="gmaps",
                id=f"gmaps/{digest}",
                name=name[:120],
                category=category,
                address=address,
                phone=phone,
                opening_hours=hours,
                rating=rating,
                reviews=reviews,
                url=url,
                query=query,
                location=location,
            )
        )
    return places


def _dismiss_consent(page: Any) -> None:
    for selector in (
        'button:has-text("Aceptar todo")',
        'button:has-text("Accept all")',
        'button:has-text("Acepto")',
        'form[action*="consent"] button',
    ):
        try:
            page.click(selector, timeout=1200)
            page.wait_for_timeout(600)
            return
        except PlaywrightError:
            continue


def _search_gmaps(
    query: str,
    *,
    location: str | None,
    limit: int,
    config: ArgosConfig,
    headless: bool | None,
) -> PlacesResult:
    full_query = f"{query} {location}".strip() if location else query
    url = f"https://www.google.com/maps/search/{quote_plus(full_query)}?hl=es"
    rows: list[dict[str, Any]] = []
    with sync_playwright() as pw:
        context = launch_context(pw, config, "gmaps", headless=headless)
        try:
            page = context.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=45000)
            _dismiss_consent(page)
            try:
                page.wait_for_selector('div[role="feed"]', timeout=20000)
            except PlaywrightError as exc:
                raise ArgosError(
                    "Google Maps no mostró el panel de resultados",
                    hint="puede ser un captcha o un cambio del DOM: probá con provider osm",
                ) from exc
            feed = page.locator('div[role="feed"]')
            for _ in range(6):
                try:
                    feed.evaluate("el => el.scrollBy(0, el.scrollHeight)")
                except PlaywrightError:
                    break
                page.wait_for_timeout(900)
            rows = list(page.evaluate(_GMAPS_EXTRACT_JS) or [])
        finally:
            context.close()
    places = _gmaps_rows_to_places(rows, query=query, location=location)[:limit]
    if not places:
        raise ArgosError(
            "Google Maps no devolvió lugares (¿captcha, consentimiento o DOM cambiado?)",
            hint="usá provider osm (gratis y estable) o revisá en modo headless=False",
        )
    return PlacesResult(
        places=places, actions=1, detail=f"{len(places)} lugares (Google Maps: {full_query!r})"
    )


# --------------------------------------------------------------------------- #
# API pública
# --------------------------------------------------------------------------- #


def search(
    query: str,
    *,
    location: str | None = None,
    radius_km: float = 5.0,
    limit: int = 25,
    provider: str = "osm",
    config: ArgosConfig | None = None,
    headless: bool | None = None,
    timeout: int = 40,
) -> PlacesResult:
    """Busca lugares por categoría/nombre.

    - ``location`` (ej: ``"Puebla, MX"``) activa búsqueda por radio con Overpass;
      sin ella se busca por nombre con Nominatim.
    - ``provider``: ``osm`` (default, gratis) o ``gmaps`` (scraping).
    """
    query = (query or "").strip()
    if not query:
        raise UsageError("falta qué buscar (ej: 'restaurantes')")
    if provider not in PROVIDERS:
        raise UsageError(
            f"proveedor desconocido: {provider!r}", hint=f"opciones: {', '.join(PROVIDERS)}"
        )
    limit = max(1, min(int(limit), 100))
    radius_km = max(0.2, min(float(radius_km), 50.0))

    if provider == "gmaps":
        config = config or ArgosConfig.load()
        return _search_gmaps(
            query, location=location, limit=limit, config=config, headless=headless
        )
    return _search_osm(
        query,
        location=location,
        radius_km=radius_km,
        limit=limit,
        timeout=timeout,
    )
