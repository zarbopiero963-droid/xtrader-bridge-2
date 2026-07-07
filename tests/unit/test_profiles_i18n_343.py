"""Test hard #343 slice 4d: localizzazione della finestra Profili impostazioni.

Puri e headless (non si costruisce la GUI: `profiles_gui` importa customtkinter).
Stesso schema del pilota Provider (#343 slice 4c): copertura EN/ES piena, parità dei
segnaposto `{name}`/`{name!r}`/`{exc}`, round-trip `.format(...)`, anti-revert."""

import ast
import os
import string

import pytest

from xtrader_bridge import i18n

_PKG = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "xtrader_bridge")
_SRC = open(os.path.join(_PKG, "profiles_gui.py"), encoding="utf-8").read()

_PROF_TR = set()
for _n in ast.walk(ast.parse(_SRC)):
    if (isinstance(_n, ast.Call) and isinstance(_n.func, ast.Attribute)
            and _n.func.attr == "tr" and _n.args
            and isinstance(_n.args[0], ast.Constant) and isinstance(_n.args[0].value, str)):
        _PROF_TR.add(_n.args[0].value)


@pytest.fixture(autouse=True)
def _ripristina_lingua():
    yield
    i18n.set_language("IT")


def _placeholders(text) -> set:
    return {name for _, name, _, _ in string.Formatter().parse(text) if name}


def test_profili_ha_stringhe_wrappate():
    assert len(_PROF_TR) >= 15
    for probe in ('text="📁  Profili impostazioni"', 'text="💾  Salva profilo"',
                  'text="↺ Carica"', 'self.title("Profili impostazioni")'):
        assert probe not in _SRC, f"stringa non wrappata: {probe}"
    for probe in ('i18n.tr("📁  Profili impostazioni")', 'i18n.tr("💾  Salva profilo")',
                  'self.title(i18n.tr("Profili impostazioni"))'):
        assert probe in _SRC, f"wrap atteso mancante: {probe}"


def test_ogni_stringa_profili_e_nel_catalogo_en_ed_es():
    for lang in ("EN", "ES"):
        table = i18n._CATALOG[lang]
        for key in _PROF_TR:
            assert key in table, f"{lang}: manca la traduzione Profili per {key!r}"
            assert table[key].strip(), f"{lang}: traduzione vuota per {key!r}"


def test_placeholder_conservati_nelle_traduzioni():
    """Template con {name}/{name!r}/{exc}: la traduzione deve avere gli STESSI campi
    (i field name, la conversione !r è cosmetica) — altrimenti .format esploderebbe."""
    for lang in ("EN", "ES"):
        table = i18n._CATALOG[lang]
        for key in _PROF_TR:
            attesi = _placeholders(key)
            if attesi:
                assert _placeholders(table[key]) == attesi, (
                    f"{lang}: segnaposto diversi in {key!r} → {table[key]!r}")


def test_format_round_trip_repr_e_exc():
    """Round-trip reale, incluso il campo con conversione !r (repr → apici)."""
    i18n.set_language("EN")
    msg = i18n.tr("✅ Profilo {name!r} salvato (senza token).").format(name="Prematch")
    assert msg == "✅ Profile 'Prematch' saved (without token)." and "{" not in msg
    i18n.set_language("ES")
    msg = i18n.tr("🗑 Profilo {name!r} eliminato.").format(name="Prematch")
    assert msg == "🗑 Perfil 'Prematch' eliminado."
    msg = i18n.tr("❌ Salvataggio profilo fallito: {exc}").format(exc="disco pieno")
    assert msg == "❌ Guardado del perfil fallido: disco pieno"
    # fallback IT: template invariato
    i18n.set_language("IT")
    assert i18n.tr("↺ Carica") == "↺ Carica"
