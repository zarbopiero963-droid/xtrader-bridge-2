"""Test hard #343 slice 4a: catalogo i18n della finestra principale.

Puri e headless. Il test anti-drift lega il catalogo al sorgente REALE di
`app.py`: una label cambiata nel codice fa fallire la suite finché il catalogo
non viene aggiornato (mai traduzioni orfane)."""

import os

import pytest

from xtrader_bridge import i18n

_APP_SRC = open(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "xtrader_bridge", "app.py"), encoding="utf-8").read()


@pytest.fixture(autouse=True)
def _ripristina_lingua():
    yield
    i18n.set_language("IT")     # stato di modulo: mai leak verso altri test


def test_default_italiano_e_tr_identita():
    assert i18n.get_language() == "IT"
    assert i18n.tr("▶  AVVIA") == "▶  AVVIA"          # IT: il catalogo non serve
    assert i18n.tr("qualunque cosa") == "qualunque cosa"


def test_set_language_fail_safe():
    assert i18n.set_language("en") == "EN"
    assert i18n.get_language() == "EN"
    assert i18n.set_language("XX") == "IT"             # non supportata → IT
    assert i18n.set_language(None) == "IT"
    assert i18n.set_language("") == "IT"               # mai scelta → comportamento storico


def test_tr_traduce_en_ed_es():
    i18n.set_language("EN")
    assert i18n.tr("▶  AVVIA") == "▶  START"
    assert i18n.tr("🧰  Strumenti") == "🧰  Tools"
    assert i18n.tr("■  STOP") == "■  STOP"             # identica in EN: fallback
    i18n.set_language("ES")
    assert i18n.tr("▶  AVVIA") == "▶  INICIAR"
    assert i18n.tr("■  STOP") == "■  DETENER"
    assert i18n.tr("🧰  Strumenti") == "🧰  Herramientas"


def test_tr_fail_safe_su_chiave_mancante():
    i18n.set_language("EN")
    assert i18n.tr("stringa mai catalogata") == "stringa mai catalogata"
    assert i18n.tr("") == ""                            # mai crash, mai None


def test_catalogo_anti_drift_chiavi_verbatim_nel_sorgente():
    """Ogni chiave del catalogo esiste VERBATIM in app.py: una label rinominata
    nel codice senza aggiornare il catalogo fa fallire QUESTO test (mai
    traduzioni orfane che l'utente EN/ES non vedrebbe più)."""
    for lang, table in i18n._CATALOG.items():
        for key in table:
            assert key in _APP_SRC, f"{lang}: chiave stantia, non in app.py: {key!r}"


def test_catalogo_valori_sensati():
    for lang, table in i18n._CATALOG.items():
        assert table, f"catalogo {lang} vuoto"
        for key, val in table.items():
            assert isinstance(val, str) and val.strip(), f"{lang}:{key!r} vuota"


def test_sorgente_usa_tr_sulle_label_catalogate():
    """Anti-regressione wiring: le label tradotte devono passare da i18n.tr nel
    sorgente (un revert del wrap le farebbe tornare hardcoded solo-IT)."""
    for probe in ('i18n.tr("▶  AVVIA")', 'i18n.tr("🧰  Strumenti")',
                  'i18n.tr("⚙️ Generale")', 'i18n.tr(label)'):
        assert probe in _APP_SRC, f"wrap mancante in app.py: {probe}"
