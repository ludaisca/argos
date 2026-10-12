"""Generación de variantes de nombre para búsqueda."""

from __future__ import annotations

from argos.variants import name_variants, split_name, username_variants


def test_split_name() -> None:
    assert split_name("Uriel Arriaga Garcia") == ["Uriel", "Arriaga", "Garcia"]
    assert split_name("  uriel.arriaga.garcia  ") == ["uriel", "arriaga", "garcia"]
    assert split_name("uriel_arriaga") == ["uriel", "arriaga"]
    assert split_name("  ") == []


def test_name_variants_full() -> None:
    assert name_variants("Uriel Arriaga Garcia") == [
        "Uriel Arriaga Garcia",
        "Uriel Arriaga",
        "Uriel Garcia",
        "Uriel Garcia Arriaga",
    ]


def test_name_variants_two_parts() -> None:
    assert name_variants("Uriel Arriaga") == ["Uriel Arriaga", "Uriel"]


def test_name_variants_single() -> None:
    assert name_variants("Uriel") == ["Uriel"]


def test_username_variants_full() -> None:
    assert username_variants("Uriel Arriaga Garcia") == [
        "urielarriagagarcia",
        "uriel.arriaga.garcia",
        "uriel_arriaga_garcia",
        "urielgarcia",
        "uriel.garcia",
        "uriel_garcia",
    ]


def test_username_variants_single() -> None:
    # una sola palabra: todas las variantes colapsan a la misma
    assert username_variants("nasa") == ["nasa"]


def test_variants_are_deduped() -> None:
    # nombres repetidos no generan variantes duplicadas
    assert name_variants("Uriel Uriel") == ["Uriel Uriel", "Uriel"]
