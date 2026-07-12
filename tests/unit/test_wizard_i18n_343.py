"""Test hard #343 slice 4h: localizzazione della finestra Wizard di prima configurazione.

Puri e headless (non si costruisce la GUI: `wizard_gui` importa customtkinter). Si verifica
il catalogo i18n e il wrapping nel sorgente, con attenzione:
- ai 5 titoli step (tupla `_TITLES`, resa via `i18n.tr(self._TITLES[step])`): sono chiavi
  del catalogo tanto quanto le stringhe wrappate direttamente;
- al messaggio TEMPLATE `{kind}` (errore imprevisto): la traduzione deve conservare il
  segnaposto, altrimenti `.format(...)` esploderebbe a runtime;
- alle esclusioni: i `res.message` di dominio bubblati da `wizard.py` (check_token/chat/
  parser/csv) restano IT (layer puro, come le altre esclusioni di dominio delle 4e/4g).
"""

import ast
import os
import string

import pytest

from xtrader_bridge import i18n

_PKG = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "xtrader_bridge")
_WIZ_SRC = open(os.path.join(_PKG, "wizard_gui.py"), encoding="utf-8").read()
_WIZ_TREE = ast.parse(_WIZ_SRC)

# Chiavi wrappate come costante di `i18n.tr(...)` (AST unisce le concatenazioni multi-linea).
_WIZ_TR = set()
for _n in ast.walk(_WIZ_TREE):
    if (isinstance(_n, ast.Call) and isinstance(_n.func, ast.Attribute)
            and _n.func.attr == "tr" and _n.args
            and isinstance(_n.args[0], ast.Constant) and isinstance(_n.args[0].value, str)):
        _WIZ_TR.add(_n.args[0].value)

# I 5 titoli step: literal della tupla `_TITLES` (resi via i18n.tr sull'elemento indicizzato).
_WIZ_TITLES = set()
for _n in ast.walk(_WIZ_TREE):
    if isinstance(_n, ast.Assign) and any(getattr(t, "id", None) == "_TITLES" for t in _n.targets):
        _WIZ_TITLES = {el.value for el in _n.value.elts
                       if isinstance(el, ast.Constant) and isinstance(el.value, str)}

_WIZ_KEYS = _WIZ_TR | _WIZ_TITLES


@pytest.fixture(autouse=True)
def _ripristina_lingua():
    yield
    i18n.set_language("IT")


def _placeholders(text) -> set:
    return {name for _, name, _, _ in string.Formatter().parse(text) if name}


def test_wizard_ha_stringhe_wrappate():
    """Sanity: il sorgente wrappa davvero titoli/pulsanti/hint (non è rimasto tutto IT)."""
    assert len(_WIZ_TR) >= 15
    assert len(_WIZ_TITLES) == 5, f"attesi 5 titoli step, trovati {_WIZ_TITLES}"
    # nessuna label/titolo hardcoded FUORI da i18n.tr
    for probe in ('title("🧙 Wizard di prima configurazione")', 'text="◀ Indietro"',
                  'text="📡 Controlla ora"', 'text=self._TITLES[self._step]'):
        assert probe not in _WIZ_SRC, f"stringa non wrappata: {probe}"
    for probe in ('self.title(i18n.tr("🧙 Wizard di prima configurazione"))',
                  'i18n.tr("◀ Indietro")', 'i18n.tr(self._TITLES[self._step])'):
        assert probe in _WIZ_SRC, f"wrap atteso mancante: {probe}"


def test_ogni_stringa_wizard_e_nel_catalogo_en_ed_es():
    """Copertura piena EN/ES: nessuna stringa chrome del wizard resta in italiano (niente UI
    mista). Include i 5 titoli step oltre alle stringhe wrappate direttamente."""
    for lang in ("EN", "ES"):
        table = i18n._CATALOG[lang]
        for key in _WIZ_KEYS:
            assert key in table, f"{lang}: manca la traduzione Wizard per {key!r}"
            assert table[key].strip(), f"{lang}: traduzione vuota per {key!r}"


def test_placeholder_conservati_nelle_traduzioni():
    """Il template `{kind}` (errore imprevisto) deve avere lo stesso segnaposto in EN/ES,
    altrimenti `.format(...)` darebbe KeyError o lascerebbe testo grezzo."""
    for lang in ("EN", "ES"):
        table = i18n._CATALOG[lang]
        for key in _WIZ_KEYS:
            attesi = _placeholders(key)
            if attesi:
                assert _placeholders(table[key]) == attesi, (
                    f"{lang}: segnaposto diversi in {key!r} → {table[key]!r}")


def test_format_round_trip_errore_imprevisto():
    """Flusso reale del fallback worker: tr(template).format(kind=…) → testo tradotto e
    interpolato, senza graffe residue."""
    i18n.set_language("EN")
    msg = i18n.tr("Verifica fallita: errore imprevisto ({kind}).").format(kind="TimeoutError")
    assert msg == "Check failed: unexpected error (TimeoutError)." and "{" not in msg
    i18n.set_language("ES")
    msg = i18n.tr("Verifica fallita: errore imprevisto ({kind}).").format(kind="ValueError")
    assert msg == "Comprobación fallida: error inesperado (ValueError)."
    # fallback IT: template invariato, interpolazione corretta
    i18n.set_language("IT")
    msg = i18n.tr("Verifica fallita: errore imprevisto ({kind}).").format(kind="KeyError")
    assert msg == "Verifica fallita: errore imprevisto (KeyError)."


def test_titoli_e_pulsanti_tradotti_en_es():
    """Spot-check verbatim su titoli e nav (severità/chiarezza preservate)."""
    i18n.set_language("EN")
    assert i18n.tr("1/5 · Token del bot") == "1/5 · Bot token"
    assert i18n.tr("Fine ✔") == "Finish ✔"
    assert i18n.tr("🔎 Verifica percorso") == "🔎 Verify path"
    i18n.set_language("ES")
    assert i18n.tr("5/5 · Checklist finale") == "5/5 · Checklist final"
    assert i18n.tr("◀ Indietro") == "◀ Atrás"
    assert i18n.tr("📡 Controlla ora") == "📡 Comprobar ahora"
