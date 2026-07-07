"""Test hard #343 slice 4c: localizzazione della finestra Anagrafica Provider.

Puri e headless (non si costruisce la GUI: `provider_gui` importa customtkinter).
Si verifica il catalogo i18n e il wrapping nel sorgente, con attenzione ai
messaggi TEMPLATE (`{name}`/`{exc}`): la traduzione deve conservare gli stessi
segnaposto, altrimenti `.format(...)` esploderebbe a runtime."""

import ast
import os
import re
import string

import pytest

from xtrader_bridge import i18n

_PKG = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "xtrader_bridge")
_PROV_SRC = open(os.path.join(_PKG, "provider_gui.py"), encoding="utf-8").read()

# Le chiavi del catalogo che appartengono alla finestra Provider: quelle presenti
# come costante tr() nel sorgente di provider_gui.py (estratte via AST così le
# concatenazioni multi-linea contano come una sola stringa).
_PROV_TR = set()
for _n in ast.walk(ast.parse(_PROV_SRC)):
    if (isinstance(_n, ast.Call) and isinstance(_n.func, ast.Attribute)
            and _n.func.attr == "tr" and _n.args
            and isinstance(_n.args[0], ast.Constant) and isinstance(_n.args[0].value, str)):
        _PROV_TR.add(_n.args[0].value)


@pytest.fixture(autouse=True)
def _ripristina_lingua():
    yield
    i18n.set_language("IT")


def _placeholders(text) -> set:
    return {name for _, name, _, _ in string.Formatter().parse(text) if name}


def test_provider_ha_stringhe_wrappate():
    """Sanity: il sorgente wrappa davvero le sue stringhe (non è rimasto tutto IT)."""
    assert len(_PROV_TR) >= 15
    # nessuna label/titolo/bottone con literal italiano FUORI da i18n.tr
    for probe in ('text="📇  Anagrafica Provider"', 'text="➕  Aggiungi"',
                  'text="🗑  Rimuovi"', 'title("Anagrafica Provider")'):
        assert probe not in _PROV_SRC, f"stringa non wrappata: {probe}"
    for probe in ('i18n.tr("📇  Anagrafica Provider")', 'i18n.tr("➕  Aggiungi")',
                  'self.title(i18n.tr("Anagrafica Provider"))'):
        assert probe in _PROV_SRC, f"wrap atteso mancante: {probe}"


def test_ogni_stringa_provider_e_nel_catalogo_en_ed_es():
    """Copertura piena EN/ES: nessuna stringa Provider resta in italiano (niente UI
    mista come segnalato su #357). Le chiavi identiche/universali sarebbero saltabili,
    ma qui tutte le stringhe Provider differiscono → devono esserci tutte."""
    for lang in ("EN", "ES"):
        table = i18n._CATALOG[lang]
        for key in _PROV_TR:
            assert key in table, f"{lang}: manca la traduzione Provider per {key!r}"
            assert table[key].strip(), f"{lang}: traduzione vuota per {key!r}"


def test_placeholder_conservati_nelle_traduzioni():
    """I template con {name}/{exc}: la traduzione DEVE avere gli stessi segnaposto,
    altrimenti .format(...) darebbe KeyError o lascerebbe testo grezzo."""
    for lang in ("EN", "ES"):
        table = i18n._CATALOG[lang]
        for key in _PROV_TR:
            attesi = _placeholders(key)
            if attesi:
                assert _placeholders(table[key]) == attesi, (
                    f"{lang}: segnaposto diversi in {key!r} → {table[key]!r}")


def test_format_round_trip_en_ed_es():
    """Il flusso reale: tr(template).format(name=...) produce testo tradotto e
    interpolato, senza graffe residue."""
    i18n.set_language("EN")
    msg = i18n.tr("➕ Provider «{name}» salvato.").format(name="Bet365")
    assert msg == "➕ Provider «Bet365» saved." and "{" not in msg
    i18n.set_language("ES")
    msg = i18n.tr("🗑 Provider «{name}» rimosso.").format(name="Bet365")
    assert msg == "🗑 Proveedor «Bet365» eliminado."
    # fallback IT: template invariato, interpolazione comunque corretta
    i18n.set_language("IT")
    msg = i18n.tr("❌ Config illeggibile: {exc}").format(exc="permessi")
    assert msg == "❌ Config illeggibile: permessi"
