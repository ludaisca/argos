"""Filtro México-only: dominios, texto y coordenadas."""

from __future__ import annotations

from argos import mexico


def test_url_country_by_domain() -> None:
    assert mexico.url_country("https://www.clinicasonrisa.mx/x") == "mx"
    assert mexico.url_country("https://imss.gob.mx/x") == "mx"
    assert mexico.url_country("https://mx.linkedin.com/in/x") == "mx"
    assert mexico.url_country("https://cl.linkedin.com/in/x") == "foreign"
    assert mexico.url_country("https://www.doctoralia.cl/perfil/x") == "foreign"
    assert mexico.url_country("https://clinica.com.co/x") == "foreign"
    assert mexico.url_country("https://algo.es/x") == "foreign"
    assert mexico.url_country("https://universidad.edu/x") == "foreign"
    assert mexico.url_country("https://www.facebook.com/pagina") == "unknown"
    assert mexico.url_country("https://es.wikipedia.org/wiki/X") == "unknown"
    assert mexico.url_country("") == "unknown"


def test_text_country_markers() -> None:
    assert mexico.text_country("Hospital en Guadalajara, Jalisco") == "mx"
    assert mexico.text_country("Médico con domicilio en Puebla") == "mx"
    assert mexico.text_country("Clínica en Bogotá") == "foreign"
    assert mexico.text_country("Médico en Santiago de Chile") == "foreign"
    assert mexico.text_country("Consulta en Madrid") == "foreign"
    assert mexico.text_country("Dr. Pérez, especialista") == "unknown"
    assert mexico.text_country("Atiende en Puebla y también en Madrid") == "unknown"


def test_hit_country_url_first() -> None:
    assert mexico.hit_country("https://x.mx/a", title="Médico", snippet="") == "mx"
    assert mexico.hit_country("https://x.cl/a", title="Hospital en México", snippet="") == "foreign"
    assert mexico.hit_country("https://x.com/a", title="Dr. X", snippet="Puebla") == "mx"


def test_coords_and_place() -> None:
    assert mexico.coords_in_mexico(19.043, -98.198)
    assert mexico.coords_in_mexico(32.5, -117.0)
    assert not mexico.coords_in_mexico(4.711, -74.072)  # Bogotá
    assert not mexico.coords_in_mexico(-33.45, -70.66)  # Santiago de Chile
