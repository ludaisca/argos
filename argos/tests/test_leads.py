"""Enriquecedor de leads: parsing, clasificación médica y pipeline (fuentes simuladas)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

import argos.leads as leads_mod
from argos import places as places_mod
from argos import searxng
from argos.config import ArgosConfig
from argos.leads import Lead, Sources, enrich_batch, enrich_lead, parse_leads, template_csv
from argos.sectors import medico

# --------------------------------------------------------------------------- #
# Parsing
# --------------------------------------------------------------------------- #


def test_parse_leads_with_header() -> None:
    text = (
        "Nombre,Correo,Teléfono,Empresa\n"
        "Char Gipt,chargipt01@gmail.com,, \n"
        ",,2221234567,Clínica Dental Sonrisa\n"
    )
    parsed = parse_leads(text)
    assert len(parsed) == 2
    assert parsed[0].nombre == "Char Gipt"
    assert parsed[0].correo == "chargipt01@gmail.com"
    assert parsed[1].telefono == "2221234567"
    assert parsed[1].empresa == "Clínica Dental Sonrisa"


def test_parse_leads_positional_and_tabs() -> None:
    text = "Juan Pérez\tjuan@mail.com\nClinica Vet Patitas, 2229998888\n"
    parsed = parse_leads(text)
    assert len(parsed) == 2
    assert parsed[0].nombre == "Juan Pérez"
    assert parsed[0].correo == "juan@mail.com"
    assert parsed[1].empresa == "Clinica Vet Patitas"
    assert parsed[1].telefono == "2229998888"


def test_parse_leads_empty() -> None:
    assert parse_leads("   \n  ") == []


def test_template_csv_roundtrip() -> None:
    parsed = parse_leads(template_csv())
    assert len(parsed) == 2
    assert parsed[0].correo == "chargipt01@gmail.com"


# --------------------------------------------------------------------------- #
# Clasificación médica
# --------------------------------------------------------------------------- #


def test_classify_clinic_is_medical() -> None:
    verdict = medico.classify(name="Clínica Dental Sonrisa", texts=["odontología integral"])
    assert verdict.sector == "medico"
    assert verdict.tipo_cliente == "Dental"
    assert "Odontología" in verdict.especialidades
    assert verdict.confidence > 0.5


def test_classify_doctor_specialty() -> None:
    verdict = medico.classify(
        name="Dr. Juan Pérez",
        texts=["Cardiólogo con consultorio en Puebla", "cita previa"],
    )
    assert verdict.sector == "medico"
    assert verdict.tipo_cliente == "Doctor"
    assert "Cardiología" in verdict.especialidades


def test_classify_hospital_and_imss() -> None:
    assert medico.classify(name="Hospital General del Norte").tipo_cliente == "Hospital"
    assert medico.classify(name="Clínica IMSS Bienestar").tipo_cliente == "IMSS BIENESTAR"
    assert (
        medico.classify(name="Clínica Veterinaria Huellitas").tipo_cliente
        == "Clinica veterinaria"
    )


def test_classify_non_medical() -> None:
    verdict = medico.classify(name="Constructora del Bajío", texts=["obras de infraestructura"])
    assert verdict.sector == "no"
    assert verdict.tipo_cliente is None


def test_all_tipo_values_are_crm_values() -> None:
    for tipo in medico.MEDICAL_TIPOS:
        assert tipo in medico.TIPOS_CLIENTE


# --------------------------------------------------------------------------- #
# Pipeline con fuentes simuladas
# --------------------------------------------------------------------------- #

SEARX_HITS = [
    searxng.SearxResult(
        title="Clínica Dental Sonrisa Puebla",
        url="https://www.clinicasonrisa.mx/contacto",
        snippet="Clínica dental en Puebla. Tel: 222 555 7788. Odontología y ortodoncia.",
    ),
    searxng.SearxResult(
        title="Clínica Dental Sonrisa | Facebook",
        url="https://www.facebook.com/clinica.dental.sonrisa",
        snippet="Página de Facebook de la clínica.",
    ),
]


def _fake_places(*args: Any, **kwargs: Any) -> places_mod.PlacesResult:
    return places_mod.PlacesResult(
        places=[
            places_mod.Place(
                source="gmaps",
                id="gmaps/abc",
                name="Clínica Dental Sonrisa",
                category="Dentista",
                address="Av. Juárez 123, Puebla",
                phone="2225557788",
                lat=19.043,
                lon=-98.198,
                url="https://www.google.com/maps/place/clinica-sonrisa",
            )
        ],
        actions=1,
        detail="1 lugar",
    )


def _fake_reverse(*args: Any, **kwargs: Any) -> dict[str, str]:
    return {"state": "Puebla", "city": "Puebla", "display": "…"}


def _sources() -> Sources:
    return Sources(
        config=ArgosConfig.load(),
        searx_base="https://searx.test",
        use_gmaps=True,
        searx_fn=lambda *args, **kwargs: list(SEARX_HITS),
        places_fn=_fake_places,
        reverse_fn=_fake_reverse,
    )


def test_enrich_lead_full() -> None:
    lead = Lead(nombre="Char Gipt", correo="chargipt01@gmail.com", empresa="Clínica Dental Sonrisa")
    enriched = enrich_lead(lead, _sources())
    assert enriched.sector == "medico"
    assert enriched.tipo_cliente == "Dental"
    assert enriched.especialidad and "Odontología" in enriched.especialidad
    assert enriched.google_maps and "google.com/maps" in enriched.google_maps
    assert enriched.categoria == "Dentista"
    assert enriched.entidad == "Puebla" and enriched.ciudad == "Puebla"
    assert enriched.apellido == "Gipt"
    assert enriched.facebook == "https://www.facebook.com/clinica.dental.sonrisa"
    assert enriched.telefono  # del snippet o de la ficha
    assert "Ramo médico: medico" in enriched.observaciones
    assert enriched.evidencia


def test_enrich_lead_non_medical() -> None:
    lead = Lead(nombre="Constructora del Bajío", telefono="2221112233")
    sources = Sources(
        config=ArgosConfig.load(),
        searx_base="https://searx.test",
        use_gmaps=False,
        searx_fn=lambda *args, **kwargs: [
            searxng.SearxResult(
                title="Constructora del Bajío",
                url="https://construcciones.example",
                snippet="Obra pública y privada.",
            )
        ],
        places_fn=_fake_places,
        reverse_fn=_fake_reverse,
    )
    enriched = enrich_lead(lead, sources)
    assert enriched.sector == "no"
    assert enriched.tipo_cliente == "No es del ramo"
    row = leads_mod.to_row(enriched)
    assert row["Ramo médico"] == "No"
    assert row["Tipo de cliente"] == "No es del ramo"


def test_enrich_batch_writes_outputs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(leads_mod.searxng, "search", lambda *args, **kwargs: list(SEARX_HITS))
    monkeypatch.setattr(leads_mod.places_mod, "search", _fake_places)
    monkeypatch.setattr(leads_mod.places_mod, "reverse_geocode", _fake_reverse)
    leads = [
        Lead(nombre="Char Gipt", correo="chargipt01@gmail.com", empresa="Clínica Dental Sonrisa"),
        Lead(nombre="Juan Pérez", telefono="2221112233"),
    ]
    summary = enrich_batch(
        leads,
        out_dir=tmp_path / "out",
        config=ArgosConfig.load(),
        use_gmaps=True,
    )
    assert summary["rows"] == 2
    assert summary["counts"]["medico"] >= 1
    assert (tmp_path / "out" / "leads.csv").is_file()
    assert (tmp_path / "out" / "leads.json").is_file()
    assert (tmp_path / "out" / "report.md").is_file()

    csv_text = (tmp_path / "out" / "leads.csv").read_text(encoding="utf-8-sig")
    assert "Tipo de cliente" in csv_text
    assert "Clínica Dental Sonrisa" in csv_text
    assert "Ramo médico" in csv_text


def test_enrich_batch_rejects_unknown_sector(tmp_path: Path) -> None:
    from argos.errors import UsageError

    with pytest.raises(UsageError):
        enrich_batch(
            [Lead(nombre="X")],
            out_dir=tmp_path,
            config=ArgosConfig.load(),
            sector="inmobiliario",
        )


def test_enrich_batch_respects_no_gmaps(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"places": 0}

    def fake_places(*args: Any, **kwargs: Any) -> Any:
        calls["places"] += 1
        raise AssertionError("gmaps no debería llamarse con use_gmaps=False")

    monkeypatch.setattr(leads_mod.searxng, "search", lambda *a, **k: list(SEARX_HITS))
    monkeypatch.setattr(leads_mod.places_mod, "search", fake_places)
    monkeypatch.setattr(leads_mod.time, "sleep", lambda _s: None)
    summary = enrich_batch(
        [Lead(nombre="Char Gipt", empresa="Clínica Dental Sonrisa")],
        out_dir=tmp_path / "o",
        config=ArgosConfig.load(),
        use_gmaps=False,
    )
    assert summary["rows"] == 1
    assert calls["places"] == 0


def test_searx_retry_recovers_empty(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    attempts = {"n": 0}

    def flaky(query: str, **kwargs: Any) -> list[searxng.SearxResult]:
        attempts["n"] += 1
        return [] if attempts["n"] == 1 else list(SEARX_HITS)

    monkeypatch.setattr(leads_mod.time, "sleep", lambda _s: None)
    sources = Sources(
        config=ArgosConfig.load(),
        searx_base="https://searx.test",
        use_gmaps=False,
        searx_fn=flaky,
        places_fn=_fake_places,
        reverse_fn=_fake_reverse,
    )
    enriched = enrich_lead(Lead(empresa="Clínica Dental Sonrisa"), sources)
    assert enriched.evidencia
    assert attempts["n"] >= 2


def test_email_signal_no_false_positive() -> None:
    verdict = medico.classify(email="rodriguezpatriciobernal@gmail.com")
    assert "correo médico" not in verdict.signals
    positive = medico.classify(email="contacto@clinica-sonrisa.mx")
    assert "correo médico" in positive.signals


def test_third_party_listings_not_used_for_specialty_or_type() -> None:
    verdict = medico.classify(
        name="Patricio Bernal",
        texts=[
            "Neurólogos recomendados - Doctoralia",
            "Listado de laboratorios de Chile (PDF)",
            "Gaceta de Madrid 1908 - Patricio Bernal Rssi",
        ],
        related_texts=["Patricio Bernal - Facebook"],
    )
    assert verdict.especialidades == []
    assert verdict.tipo_cliente is None


def test_related_texts_enable_type_and_specialty() -> None:
    verdict = medico.classify(
        name="Clínica Dental Sonrisa",
        texts=["Directorio genérico"],
        related_texts=["Clínica Dental Sonrisa | Puebla", "Odontología y ortodoncia"],
    )
    assert verdict.tipo_cliente == "Dental"
    assert "Odontología" in verdict.especialidades


def test_enrich_batch_pauses_between_batches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(leads_mod.searxng, "search", lambda *a, **k: list(SEARX_HITS))
    monkeypatch.setattr(leads_mod.places_mod, "search", _fake_places)
    monkeypatch.setattr(leads_mod.places_mod, "reverse_geocode", _fake_reverse)
    pauses: list[float] = []
    leads = [Lead(nombre=f"Persona {index}") for index in range(3)]
    summary = enrich_batch(
        leads,
        out_dir=tmp_path / "tandas",
        config=ArgosConfig.load(),
        use_gmaps=False,
        batch_size=2,
        pause_seconds=120.0,
        sleep_fn=pauses.append,
    )
    assert summary["rows"] == 3
    assert pauses == [120.0]


def test_empty_sources_mark_dudoso_not_no(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(leads_mod.time, "sleep", lambda _s: None)
    sources = Sources(
        config=ArgosConfig.load(),
        searx_base="https://searx.test",
        use_gmaps=False,
        searx_fn=lambda *args, **kwargs: [],
        places_fn=_fake_places,
        reverse_fn=_fake_reverse,
    )
    enriched = enrich_lead(Lead(nombre="Patricio Bernal", telefono="9541235609"), sources)
    assert enriched.sector == "dudoso"
    assert "Sin resultados" in enriched.observaciones
    assert enriched.tipo_cliente is None


def test_snippet_only_mentions_do_not_enrich(monkeypatch: pytest.MonkeyPatch) -> None:
    hits = [
        searxng.SearxResult(
            title="Neurólogos recomendados - Directorio médico",
            url="https://directorio.example/neurologos",
            snippet="Manuel Patricio Bernal Berk, Neurólogo. Laboratorio clínico asociado.",
        )
    ]
    sources = Sources(
        config=ArgosConfig.load(),
        searx_base="https://searx.test",
        use_gmaps=False,
        searx_fn=lambda *args, **kwargs: list(hits),
        places_fn=_fake_places,
        reverse_fn=_fake_reverse,
    )
    enriched = enrich_lead(Lead(nombre="Patricio Bernal"), sources)
    assert enriched.tipo_cliente is None
    assert enriched.especialidad is None


def test_person_lead_skips_gmaps(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"places": 0}

    def fake_places(*args: Any, **kwargs: Any) -> Any:
        calls["places"] += 1
        raise AssertionError("gmaps no aplica para una persona sin empresa")

    monkeypatch.setattr(leads_mod.searxng, "search", lambda *a, **k: list(SEARX_HITS))
    monkeypatch.setattr(leads_mod.places_mod, "search", fake_places)
    monkeypatch.setattr(leads_mod.time, "sleep", lambda _s: None)
    summary = enrich_batch(
        [Lead(nombre="Patricio Bernal")],
        out_dir=tmp_path / "o2",
        config=ArgosConfig.load(),
        use_gmaps=True,
    )
    assert summary["rows"] == 1
    assert calls["places"] == 0
