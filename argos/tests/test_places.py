"""Lugares: Nominatim/Overpass (OSM), parsing de Google Maps e integración con research."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

import argos.places as places_mod
from argos.config import ArgosConfig
from argos.errors import ArgosError, UsageError
from argos.models import Place
from argos.places import category_filters, geocode, search

NOMINATIM_CAFE = [
    {
        "name": "Café Roma",
        "display_name": "Café Roma, Calle 5 de Mayo 123, Puebla, México",
        "lat": "19.0430",
        "lon": "-98.1980",
        "osm_type": "node",
        "osm_id": 123456,
        "type": "cafe",
    }
]

OVERPASS_CAFES: dict[str, Any] = {
    "elements": [
        {
            "type": "node",
            "id": 1,
            "lat": 19.0425,
            "lon": -98.1975,
            "tags": {
                "name": "Café Central",
                "amenity": "cafe",
                "addr:street": "Av. Juárez",
                "addr:housenumber": "45",
                "addr:city": "Puebla",
                "phone": "+52 222 123 4567",
                "opening_hours": "Mo-Su 08:00-22:00",
            },
        },
        {
            "type": "way",
            "id": 2,
            "center": {"lat": 19.046, "lon": -98.195},
            "tags": {"name": "Café Lejos", "amenity": "cafe", "website": "https://cafe.example"},
        },
        {
            "type": "node",
            "id": 3,
            "lat": 19.0426,
            "lon": -98.1976,
            "tags": {"amenity": "cafe"},
        },
    ]
}


def test_geocode_parses_nominatim(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: dict[str, Any] = {}

    def fake_get(url: str, params: dict[str, Any], *, timeout: int) -> Any:
        calls["params"] = params
        return [{"display_name": "Puebla, México", "lat": "19.04", "lon": "-98.19"}]

    monkeypatch.setattr(places_mod, "_get_json", fake_get)
    point = geocode("Puebla, MX")
    assert point is not None
    assert point.lat == pytest.approx(19.04)
    assert point.lon == pytest.approx(-98.19)
    assert calls["params"]["q"] == "Puebla, MX"


def test_geocode_empty_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(places_mod, "_get_json", lambda *a, **k: [])
    assert geocode("Narnia") is None


def test_category_filters_known_and_name_fallback() -> None:
    assert '["amenity"="cafe"]' in category_filters("Cafeterías")
    filters = category_filters("Taquería Doña Pelos")
    assert filters[0].startswith('["name"~')
    assert "Taquería" in filters[0]


def test_search_osm_with_location(monkeypatch: pytest.MonkeyPatch) -> None:
    posts: dict[str, Any] = {}

    def fake_get(url: str, params: dict[str, Any], *, timeout: int) -> Any:
        return [
            {
                "display_name": "Puebla, México",
                "lat": "19.04",
                "lon": "-98.19",
                "osm_type": "relation",
                "osm_id": 1,
            }
        ]

    def fake_post(url: str, payload: dict[str, Any], *, timeout: int) -> Any:
        posts["data"] = payload["data"]
        return OVERPASS_CAFES

    monkeypatch.setattr(places_mod, "_get_json", fake_get)
    monkeypatch.setattr(places_mod, "_post_form", fake_post)

    result = search("cafeterías", location="Puebla, MX", radius_km=3, limit=10)
    assert len(result.places) == 2  # el POI sin nombre se descarta
    assert result.actions == 2
    assert result.center is not None and result.center.lat == pytest.approx(19.04)
    assert '["amenity"="cafe"]' in posts["data"]
    assert "around:3000" in posts["data"]

    central = next(place for place in result.places if place.name == "Café Central")
    assert central.address == "Av. Juárez 45, Puebla"
    assert central.phone == "+52 222 123 4567"
    assert central.opening_hours == "Mo-Su 08:00-22:00"
    assert central.distance_km is not None
    assert central.url == "https://www.openstreetmap.org/node/1"

    lejos = next(place for place in result.places if place.name == "Café Lejos")
    assert lejos.website == "https://cafe.example"
    assert lejos.url == "https://www.openstreetmap.org/way/2"

    # ordenados por distancia
    distances = [place.distance_km for place in result.places]
    assert distances == sorted(distances)


def test_search_without_location_uses_nominatim(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_get(url: str, params: dict[str, Any], *, timeout: int) -> Any:
        return NOMINATIM_CAFE

    def fail_post(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("sin location no debe llamar a Overpass")

    monkeypatch.setattr(places_mod, "_get_json", fake_get)
    monkeypatch.setattr(places_mod, "_post_form", fail_post)

    result = search("Café Roma", limit=5)
    assert result.actions == 1
    assert result.places[0].name == "Café Roma"
    assert result.places[0].source == "osm"
    assert result.places[0].url == "https://www.openstreetmap.org/node/123456"


def test_search_unknown_provider_rejected() -> None:
    with pytest.raises(UsageError):
        search("cafés", provider="bing")


def test_search_empty_query_rejected() -> None:
    with pytest.raises(UsageError):
        search("   ")


def test_search_unlocatable_zone_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(places_mod, "_get_json", lambda *a, **k: [])
    with pytest.raises(ArgosError, match="no pude ubicar"):
        search("cafeterías", location="Narnia")


def test_gmaps_rows_to_places_parses() -> None:
    rows = [
        {
            "name": "Café Roma",
            "url": "https://maps.google.com/?cid=1",
            "text": (
                "Café Roma\n4,6(258)\nCafetería\nAv. Juárez 123, Puebla\n"
                "Abierto ⋅ Cierra a las 22:00\n+52 222 555 0101"
            ),
        }
    ]
    places = places_mod._gmaps_rows_to_places(rows, query="cafés", location="Puebla")
    assert len(places) == 1
    place = places[0]
    assert place.source == "gmaps"
    assert place.rating == pytest.approx(4.6)
    assert place.reviews == 258
    assert place.category == "Cafetería"
    assert place.address == "Av. Juárez 123, Puebla"
    assert place.phone == "+52 222 555 0101"
    assert "Abierto" in (place.opening_hours or "")


def test_gmaps_splits_category_and_address_line() -> None:
    rows = [
        {
            "name": "Café Cultura",
            "url": "https://maps.google.com/?cid=2",
            "text": (
                "Café Cultura\n4,8(120)\nCafetería · C. 4 Sur 506\n"
                "Cerrado ⋅ Abre a las 9:00"
            ),
        }
    ]
    places = places_mod._gmaps_rows_to_places(rows, query="cafés", location="Puebla")
    assert len(places) == 1
    place = places[0]
    assert place.category == "Cafetería"
    assert place.address == "C. 4 Sur 506"
    assert place.rating == pytest.approx(4.8)
    assert place.reviews == 120


def test_gmaps_rating_variants() -> None:
    rows = [
        {
            "name": "Café Tormenta",
            "url": "https://maps.google.com/?cid=3",
            "rating_label": "3,8 estrellas",
            "text": (
                "Café Tormenta\nCafé Tormenta\n3,8\n"
                "Cafetería · Puebla Mérida esquina, Puebla 90\n"
                "Abierto · Cierra a las 6 p.m."
            ),
        },
        {
            "name": "Otro Café",
            "url": "https://maps.google.com/?cid=4",
            "rating_label": "4,5 estrellas, 320 reseñas",
            "text": "Otro Café\n4,5\nCafetería\nCalle 2\nCerrado",
        },
    ]
    places = places_mod._gmaps_rows_to_places(rows)
    assert len(places) == 2

    tormenta = places[0]
    assert tormenta.rating == pytest.approx(3.8)
    assert tormenta.reviews is None
    assert tormenta.category == "Cafetería"
    assert tormenta.address == "Puebla Mérida esquina, Puebla 90"

    otro = places[1]
    assert otro.rating == pytest.approx(4.5)
    assert otro.reviews == 320


PHOTON_FEATURES: dict[str, Any] = {
    "features": [
        {
            "geometry": {"coordinates": [-98.1975, 19.0425]},
            "properties": {
                "name": "Café Fotón",
                "osm_type": "N",
                "osm_id": 555,
                "osm_value": "cafe",
                "street": "Av. Juárez",
                "housenumber": "45",
                "city": "Puebla",
            },
        },
        {
            "geometry": {"coordinates": [-98.9, 19.9]},
            "properties": {"name": "Café Lejísimos", "osm_type": "N", "osm_id": 777},
        },
    ]
}


def test_overpass_falls_back_to_photon(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def fake_get(
        url: str, params: dict[str, Any] | list[tuple[str, str]], *, timeout: int
    ) -> Any:
        if "photon" in url:
            captured["photon_params"] = params
            return PHOTON_FEATURES
        return [
            {
                "display_name": "Puebla de Zaragoza, México",
                "lat": "19.0425",
                "lon": "-98.1975",
                "addresstype": "city",
            }
        ]

    def failing_post(url: str, payload: dict[str, Any], *, timeout: int) -> Any:
        raise ArgosError("overpass saturado (504)")

    monkeypatch.setattr(places_mod, "_get_json", fake_get)
    monkeypatch.setattr(places_mod, "_post_form", failing_post)
    monkeypatch.setattr(places_mod, "OVERPASS_ENDPOINTS", ("https://overpass.test/api",))
    monkeypatch.setattr(places_mod.time, "sleep", lambda _seconds: None)

    result = search("cafeterías", location="Puebla, MX", radius_km=3, limit=10)
    assert len(result.places) == 1
    place = result.places[0]
    assert place.name == "Café Fotón"
    assert place.id == "node/555"
    assert place.url == "https://www.openstreetmap.org/node/555"
    assert "Photon" in result.detail

    params = captured["photon_params"]
    assert isinstance(params, list)
    assert ("osm_tag", "amenity:cafe") in params


def test_run_research_places_target(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from argos.research import run_research

    def fake_search(query: str, **kwargs: Any) -> places_mod.PlacesResult:
        return places_mod.PlacesResult(
            places=[
                Place(
                    source="osm",
                    id="node/1",
                    name="Café Central",
                    query=query,
                    location=kwargs.get("location"),
                )
            ],
            actions=2,
            detail="1 lugar",
        )

    monkeypatch.setattr(places_mod, "search", fake_search)
    plan = tmp_path / "plan.yaml"
    plan.write_text(
        "job: lugares\nheadless: true\ntargets:\n"
        "  - type: places_search\n    value: cafeterías\n    kind: Puebla, MX\n    limit: 5\n",
        encoding="utf-8",
    )
    result = run_research(plan, base_dir=tmp_path / "out", config=ArgosConfig.load())
    assert result["results"][0]["status"] == "ok"
    assert result["results"][0]["written"]["places"] == 1

    job_dir = Path(result["job_dir"])
    assert (job_dir / "places.jsonl").is_file()
    assert (job_dir / "places.csv").is_file()
    report = (job_dir / "report.md").read_text(encoding="utf-8")
    assert "## Lugares" in report
    assert "Café Central" in report
