"""Test hard #343 slice 4f: localizzazione della finestra Diario.

Puri e headless. Oltre alla copertura EN/ES e parità segnaposto, verifica che i
valori-filtro «(tutti i tipi)»/«Tutti» — display MA anche chiavi — siano tradotti
alla COSTRUZIONE e confrontati con lo stesso valore tradotto (il filtro «tutti i
tipi» → nessun filtro deve funzionare in ogni lingua)."""

import ast
import os
import string

import pytest

from xtrader_bridge import i18n

_PKG = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "xtrader_bridge")
with open(os.path.join(_PKG, "journal_view_gui.py"), encoding="utf-8") as _fh:
    _SRC = _fh.read()

_J_TR = set()
for _n in ast.walk(ast.parse(_SRC)):
    if (isinstance(_n, ast.Call) and isinstance(_n.func, ast.Attribute)
            and _n.func.attr == "tr" and _n.args
            and isinstance(_n.args[0], ast.Constant) and isinstance(_n.args[0].value, str)):
        _J_TR.add(_n.args[0].value)


@pytest.fixture(autouse=True)
def _ripristina_lingua():
    yield
    i18n.set_language("IT")


def _placeholders(text) -> set:
    return {name for _, name, _, _ in string.Formatter().parse(text) if name}


def test_chrome_wrappata():
    assert len(_J_TR) >= 10
    for probe in ('text="📒  Diario eventi (locale, sola lettura)"',
                  'text="Quando"', 'label_text="Eventi del diario"'):
        assert probe not in _SRC, f"stringa non wrappata: {probe}"
    for probe in ('i18n.tr("📒  Diario eventi (locale, sola lettura)")',
                  'i18n.tr("(tutti i tipi)")', 'i18n.tr("Tutti")', 'i18n.tr("Quando")'):
        assert probe in _SRC, f"wrap atteso mancante: {probe}"


def test_ogni_stringa_diario_e_nel_catalogo_en_ed_es():
    for lang in ("EN", "ES"):
        table = i18n._CATALOG[lang]
        for key in _J_TR:
            assert key in table, f"{lang}: manca la traduzione Diario per {key!r}"
            assert table[key].strip(), f"{lang}: traduzione vuota per {key!r}"


def test_placeholder_conservati():
    for lang in ("EN", "ES"):
        table = i18n._CATALOG[lang]
        for key in _J_TR:
            attesi = _placeholders(key)
            if attesi:
                assert _placeholders(table[key]) == attesi, (
                    f"{lang}: segnaposto diversi in {key!r}")


def test_traduzioni_filtro_per_lingua():
    """«(tutti i tipi)» tradotto per lingua (il test di coerenza col confronto
    `_selected_types`, che richiede il modulo GUI, vive in test_journal_view_gui.py)."""
    i18n.set_language("EN")
    assert i18n.tr("(tutti i tipi)") == "(all types)" and i18n.tr("Tutti") == "All"
    i18n.set_language("ES")
    assert i18n.tr("(tutti i tipi)") == "(todos los tipos)"


def test_format_conteggi_e_errore():
    i18n.set_language("EN")
    assert (i18n.tr("Diario: {tot} eventi totali (mostrati {shown}).")
            .format(tot=10, shown=3) == "Journal: 10 total events (showing 3).")
    assert (i18n.tr("⚠️ Errore lettura diario: {kind}").format(kind="OSError")
            == "⚠️ Journal read error: OSError")
